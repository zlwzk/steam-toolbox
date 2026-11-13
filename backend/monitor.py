"""更新监控模块：关注游戏 / Mod 的更新检测、事件流与规则自动订阅。

设计要点（见 docs/MONITORING.md）：
- 只读监控走 Web API Key（GetDetails / QueryFiles / appdetails），无需浏览器登录态。
- 订阅动作复用持久化浏览器 Profile 与拟人节奏，与工坊模块同一套安全策略。
- 所有目标、规则、事件仅存本机数据库，不上传、不收集。
- 商店公开接口不提供可执行文件版本号；本体以商店信息指纹变化为准，不虚构版本号。
"""
from __future__ import annotations

import datetime as dt
import json
import threading
import time

from fastapi import HTTPException

from . import claimer, config, database, logstore, notify
from .steam_client import RateLimited, SteamApiError, SteamClient, StoreBlocked
from .throttler import ThrottleConfig, Throttler

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None

monitor_progress: dict = {
    "state": "idle",
    "total": 0,
    "current": 0,
    "message": "",
    "counts": {"game_update": 0, "mod_new": 0, "mod_update": 0, "rule_hit": 0,
               "subscribed": 0, "failed": 0},
    "started_at": None,
    "finished_at": None,
}
_lock = threading.Lock()
_stop = threading.Event()
_thread: threading.Thread | None = None

# 订阅请求脚本：在页面上下文内调用 Steam 原生订阅接口，携带登录 Cookie。
SUBSCRIBE_JS = r"""
async ({ id, appid }) => {
  const sessionid = (document.cookie.match(/(?:^|;\s*)sessionid=([^;]+)/) || [])[1] || '';
  const resp = await fetch('https://steamcommunity.com/sharedfiles/subscribe', {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8' },
    body: new URLSearchParams({ id, appid: appid || '', sessionid }).toString(),
  });
  let j = null;
  const text = await resp.text();
  try { j = JSON.parse(text); } catch (e) { j = null; }
  return {
    redirected: resp.redirected && /login/i.test(resp.url),
    status: resp.status,
    success: j ? String(j.success) === '1' : null,
    isHtml: !j,
  };
}
"""


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _update(**kwargs) -> None:
    with _lock:
        monitor_progress.update(kwargs)


def get_progress() -> dict:
    with _lock:
        return dict(monitor_progress)


# ---------- 输入校验 ----------

def _valid_appid(appid: str | int) -> int:
    s = str(appid).strip()
    if not s.isdecimal() or len(s) > 12 or int(s) < 1:
        raise HTTPException(status_code=400, detail="AppID 应为正整数")
    return int(s)


def _valid_file_id(file_id: str | int) -> int:
    s = str(file_id).strip()
    if not s.isdecimal() or len(s) > 14 or int(s) < 1:
        raise HTTPException(status_code=400, detail="工坊文件 ID 应为正整数")
    return int(s)


def _normalize_keywords(raw: str) -> str:
    parts = [k.strip().lower() for k in str(raw or "").replace("，", ",").split(",") if k.strip()]
    if not parts:
        raise HTTPException(status_code=400, detail="至少填写一个关键字")
    if len(",".join(parts)) > 500:
        raise HTTPException(status_code=400, detail="关键字过长")
    return ",".join(dict.fromkeys(parts))


# ---------- 指纹与规则匹配 ----------

def _store_fingerprint(body: dict | None) -> str | None:
    """从商店详情体构造本体信息指纹；无详情返回 None。"""
    if not body:
        return None
    price = (body.get("price_overview") or {}).get("final")
    dlc = sorted(str(x) for x in (body.get("dlc") or []))
    release = (body.get("release_date") or {}).get("date") or ""
    langs = body.get("supported_languages") or ""
    return "|".join([
        str(body.get("name") or ""),
        str(body.get("type") or ""),
        str(price if price is not None else ""),
        ",".join(dlc),
        str(release),
        str(body.get("header_image") or ""),
        str(len(langs)),
    ])


def _rule_matches(rule: dict, title: str, tags: list[str], appid: int) -> list[str]:
    """返回命中的关键字列表；未命中返回空列表。appid=0 规则匹配任意游戏。"""
    if not rule.get("enabled"):
        return []
    if rule.get("appid") and int(rule["appid"]) != appid:
        return []
    kws = [k for k in str(rule.get("keywords") or "").split(",") if k]
    if not kws:
        return []
    hay = (str(title or "") + " " + " ".join(tags or [])).lower()
    hits = [k for k in kws if k in hay]
    if rule.get("match_mode") == "all":
        return hits if len(hits) == len(kws) else []
    return hits


# ---------- 目标 / 规则 CRUD（路由层调用） ----------

def add_game(appid: str | int, watch_store: bool, watch_workshop: bool) -> dict:
    aid = _valid_appid(appid)
    database.upsert_watch_game(aid, watch_store=1 if watch_store else 0,
                               watch_workshop=1 if watch_workshop else 0)
    return {"ok": True, "appid": aid}


def add_mod(file_id: str | int, appid: str | int = 0) -> dict:
    fid = _valid_file_id(file_id)
    aid = _valid_appid(appid) if str(appid).strip() not in ("", "0") else 0
    database.upsert_watch_mod(fid, aid)
    return {"ok": True, "file_id": fid, "appid": aid}


def add_rule(appid: str | int, keywords: str, match_mode: str,
             auto_subscribe: bool, enabled: bool, note: str) -> dict:
    aid = _valid_appid(appid) if str(appid).strip() not in ("", "0") else 0
    if match_mode not in ("any", "all"):
        raise HTTPException(status_code=400, detail="匹配模式仅支持 any / all")
    kw = _normalize_keywords(keywords)
    rid = database.add_watch_rule(aid, kw, match_mode, 1 if auto_subscribe else 0,
                                  1 if enabled else 0, (note or "").strip()[:200])
    return {"ok": True, "id": rid}


# ---------- 检测流程 ----------

def _detect_store(client: SteamClient, game: dict) -> list[dict]:
    """检测本体商店信息变化，返回事件字典列表。"""
    events: list[dict] = []
    body = client.get_appdetails(game["appid"])
    fingerprint = _store_fingerprint(body)
    name = (body or {}).get("name") or game.get("name") or ""
    cover = SteamClient.pick_cover(game["appid"], (body or {}).get("header_image"), None)
    if name:
        database.upsert_watch_game(game["appid"], name=name, cover_url=cover,
                                   watch_store=game["watch_store"],
                                   watch_workshop=game["watch_workshop"])
    old = game.get("last_fingerprint")
    if old is None:
        database.update_watch_game_snapshot(game["appid"], fingerprint,
                                             game.get("last_workshop_top"), "首次建档")
        return events
    if fingerprint != old:
        detail = "商店信息有变化（名称 / 价格 / DLC / 发行日期 / 封面等）"
        eid = database.add_watch_event("game_store_update", game["appid"], None,
                                        name or f"#{game['appid']}", detail)
        events.append({"event_id": eid, "kind": "game_store_update", "appid": game["appid"],
                       "file_id": None, "title": name, "detail": detail})
        database.update_watch_game_snapshot(game["appid"], fingerprint,
                                            game.get("last_workshop_top"), detail)
    else:
        database.update_watch_game_snapshot(game["appid"], fingerprint,
                                            game.get("last_workshop_top"), "无变化")
    return events


def _detect_workshop(client: SteamClient, game: dict) -> list[dict]:
    """检测工坊最近更新 / 新上架 Mod，返回事件字典列表。"""
    events: list[dict] = []
    top_n = max(1, min(50, int(database.get_setting("watch_workshop_top", "20"))))
    try:
        result = client.query_workshop(game["appid"], num_per_page=top_n)
    except (RateLimited, StoreBlocked, SteamApiError) as exc:
        logstore.add("WARN", f"工坊列表查询失败（AppID {game['appid']}）：{exc}")
        return events
    items = result.get("items") or []
    snapshot = {str(it["file_id"]): it["time_updated"] for it in items}
    new_top = json.dumps(snapshot, sort_keys=True)

    old_top = game.get("last_workshop_top")
    old: dict[str, int] = {}
    if old_top:
        try:
            old = json.loads(old_top)
        except (ValueError, TypeError):
            old = {}

    if not old:
        # 首次建档：仅保存当前工坊基线，不把首屏 Mod 误报为「新上架」；
        # 下一次检测起才对比出新增 / 更新。
        database.update_watch_game_snapshot(game["appid"], game.get("last_fingerprint"),
                                            new_top, "首次建档")
        return events

    rules = database.list_watch_rules()
    auto_sub_global = database.get_setting("watch_auto_subscribe", "false").lower() == "true"
    auto_queue: list[dict] = []

    for it in items:
        fid = it["file_id"]
        old_ts = int(old.get(str(fid), 0))
        if str(fid) not in old:
            kind = "mod_new"
            detail = "工坊新上架 Mod"
        elif it["time_updated"] > old_ts:
            kind = "mod_update"
            detail = f"Mod 有更新（更新时间戳 {it['time_updated']}）"
        else:
            continue

        # 规则命中判定
        hit_rules = [r for r in rules if _rule_matches(r, it["title"], it["tags"], game["appid"])]
        action = "none"
        if hit_rules:
            action = "rule_hit"
            kw = sorted({k for r in hit_rules for k in r["keywords"].split(",") if k})
            detail += f"；命中关键字：{', '.join(kw)}"
            if auto_sub_global and any(r["auto_subscribe"] for r in hit_rules):
                auto_queue.append({"file_id": fid, "appid": game["appid"], "title": it["title"]})

        eid = database.add_watch_event(kind, game["appid"], fid, it["title"], detail, action=action)
        events.append({"event_id": eid, "kind": kind, "appid": game["appid"],
                       "file_id": fid, "title": it["title"], "detail": detail,
                       "auto": action == "rule_hit" and bool(auto_queue)})

    database.update_watch_game_snapshot(game["appid"], game.get("last_fingerprint"),
                                        new_top, "工坊已巡检")
    if auto_queue:
        _enqueue_auto_subscribe(auto_queue)
    return events


def _detect_watch_mods(client: SteamClient) -> list[dict]:
    events: list[dict] = []
    mods = database.list_watch_mods()
    if not mods:
        return events
    details = client.get_workshop_details([m["published_file_id"] for m in mods])
    for m in mods:
        info = details.get(m["published_file_id"])
        if not info:
            continue
        old_ts = int(m.get("last_time_updated") or m.get("time_updated") or 0)
        old_size = int(m.get("last_file_size") or m.get("file_size") or 0)
        changed = info["time_updated"] > old_ts or info["file_size"] > old_size
        note = ""
        if changed:
            note = "Mod 有更新" + (f"（大小 {old_size} → {info['file_size']} 字节）"
                                  if info["file_size"] != old_size else "")
            eid = database.add_watch_event("mod_update", info["appid"] or m["appid"],
                                            m["published_file_id"], info["title"], note)
            events.append({"event_id": eid, "kind": "mod_update", "appid": info["appid"],
                           "file_id": m["published_file_id"], "title": info["title"], "detail": note})
        database.update_watch_mod_snapshot(m["published_file_id"], info["file_size"],
                                            info["time_updated"], note or "无变化")
    return events


def run_check() -> dict:
    """启动一次后台检测；已有检测在跑时拒绝重复启动。"""
    if monitor_progress["state"] == "running":
        return {"ok": False, "error": "监控检测正在进行中"}
    s = database.get_settings()
    if not (s.get("api_key") and s.get("steamid")):
        return {"ok": False, "error": "请先在「账号绑定」填入 API Key 与 SteamID"}
    _update(state="running", total=0, current=0, message="正在启动监控检测…",
            counts={"game_update": 0, "mod_new": 0, "mod_update": 0, "rule_hit": 0,
                    "subscribed": 0, "failed": 0},
            started_at=_now(), finished_at=None)
    threading.Thread(target=_check_worker, daemon=True).start()
    return {"ok": True}


def _check_worker() -> None:
    client = SteamClient.from_settings()
    counts = {"game_update": 0, "mod_new": 0, "mod_update": 0, "rule_hit": 0,
              "subscribed": 0, "failed": 0}
    games = database.list_watch_games()
    total = len(games) + len(database.list_watch_mods())
    _update(total=total, current=0)
    logstore.add("INFO", f"监控检测开始：关注游戏 {len(games)} 个，关注 Mod {len(database.list_watch_mods())} 个")

    try:
        for game in games:
            if monitor_progress["state"] != "running":
                break
            _update(current=monitor_progress["current"] + 1,
                    message=f"正在检测游戏 #{game['appid']}")
            try:
                if game["watch_store"]:
                    for e in _detect_store(client, game):
                        counts[e["kind"]] = counts.get(e["kind"], 0) + 1
                if game["watch_workshop"]:
                    for e in _detect_workshop(client, game):
                        counts[e["kind"]] = counts.get(e["kind"], 0) + 1
                        if e["action"] == "rule_hit":
                            counts["rule_hit"] += 1
            except (RateLimited, StoreBlocked) as exc:
                logstore.add("WARN", f"监控检测受阻：{exc}")
                _update(state="blocked", message=f"检测受阻：{exc}", finished_at=_now())
                return
            except SteamApiError as exc:
                logstore.add("WARN", f"监控检测异常（AppID {game['appid']}）：{exc}")
            time.sleep(0.5)

        for e in _detect_watch_mods(client):
            counts[e["kind"]] = counts.get(e["kind"], 0) + 1

        _update(state="done", message="监控检测完成", finished_at=_now(), counts=counts)
        logstore.add("INFO", f"监控检测完成：{counts}")
        notify.notify("监控检测完成", f"更新事件统计：{counts}")
    except Exception as exc:  # noqa: BLE001 - 后台线程不能因单次异常退出调度
        logstore.add("ERROR", f"监控检测异常：{exc}")
        _update(state="error", message=f"检测异常：{exc}", finished_at=_now())


# ---------- 订阅（复用浏览器登录态） ----------

_sub_queue: list[dict] = []
_sub_lock = threading.Lock()


def _enqueue_auto_subscribe(items: list[dict]) -> None:
    with _sub_lock:
        existing = {x["file_id"] for x in _sub_queue}
        for it in items:
            if it["file_id"] not in existing:
                _sub_queue.append(it)
                existing.add(it["file_id"])


def subscribe_items(items: list[dict]) -> dict:
    """一键订阅一组 Mod：[{file_id, appid, title}]。后台串行，拟人节奏。"""
    clean: list[dict] = []
    seen: set[int] = set()
    for it in items:
        fid = _valid_file_id(it.get("file_id"))
        aid = _valid_appid(it.get("appid")) if str(it.get("appid") or "0").strip() not in ("", "0") else 0
        if fid in seen:
            continue
        seen.add(fid)
        clean.append({"file_id": fid, "appid": aid, "title": str(it.get("title") or f"#{fid}")})
    if not clean:
        return {"ok": False, "error": "没有可订阅的 Mod"}
    s = database.get_settings()
    if not (s.get("api_key") and s.get("steamid")):
        return {"ok": False, "error": "请先完成账号绑定与浏览器登录"}
    with _sub_lock:
        for it in clean:
            if it["file_id"] not in {x["file_id"] for x in _sub_queue}:
                _sub_queue.append(it)
    threading.Thread(target=_subscribe_worker, daemon=True).start()
    return {"ok": True, "count": len(clean)}


def _subscribe_worker() -> None:
    if sync_playwright is None:
        _update(message="未安装 Playwright", state="error")
        return
    s = database.get_settings()
    thr = Throttler(ThrottleConfig(
        delay_min=float(s.get("ws_delay_min", 2.5)),
        delay_max=float(s.get("ws_delay_max", 5.0)),
        max_retries=int(s.get("ws_max_retries", 3)),
    ))
    headless = s.get("claim_headless", "false").lower() == "true"
    channel_pref = s.get("browser_channel", "msedge")

    with _sub_lock:
        items = list(_sub_queue)
        _sub_queue.clear()

    if not items:
        return

    counts = {"subscribed": 0, "failed": 0}
    _update(state="running", total=len(items), current=0, message="正在订阅监控命中的 Mod…",
            counts={**monitor_progress["counts"], **counts})

    with sync_playwright() as pw:
        try:
            context, browser_label, _real = claimer._launch_context(pw, headless, channel_pref)
        except Exception as exc:  # noqa: BLE001
            logstore.add("ERROR", f"订阅浏览器启动失败：{exc}")
            _update(state="error", message=f"浏览器启动失败：{exc}", finished_at=_now())
            return

        try:
            page = context.pages[0] if context.pages else context.new_page()
            for idx, it in enumerate(items, start=1):
                thr.wait_random_delay()
                _update(current=idx, message=f"[{idx}/{len(items)}] 订阅 {it['title']}")
                try:
                    page.goto(f"https://steamcommunity.com/sharedfiles/filedetails/?id={it['file_id']}",
                              wait_until="domcontentloaded", timeout=30000)
                    page.wait_for_timeout(1000)
                    res = page.evaluate(SUBSCRIBE_JS, {"id": str(it["file_id"]),
                                                        "appid": str(it["appid"])})
                    if res.get("redirected") or res.get("isHtml"):
                        raise claimer.ClaimError("登录态失效，请重新登录 Steam")
                    if res.get("status") == 429 or (res.get("status") or 0) >= 500:
                        raise claimer.ClaimError(f"http {res['status']}")
                    if res.get("success"):
                        counts["subscribed"] += 1
                        database.mark_watch_mod_subscribed(it["file_id"], 1)
                        database.add_watch_event("subscribe", it["appid"], it["file_id"],
                                                 it["title"], "已自动/手动订阅", action="subscribed")
                        logstore.add("INFO", f"[订阅成功] {it['title']}")
                    else:
                        counts["failed"] += 1
                        logstore.add("WARN", f"[订阅失败] {it['title']}：Steam 返回未成功")
                except Exception as exc:  # noqa: BLE001
                    counts["failed"] += 1
                    logstore.add("WARN", f"[订阅异常] {it['title']}：{exc}")
                _update(counts={**monitor_progress["counts"], **counts})
            _update(state="done", message="订阅完成", finished_at=_now(),
                    counts={**monitor_progress["counts"], **counts})
        finally:
            context.close()


# ---------- 定时巡检调度 ----------

def _tick() -> None:
    enabled = database.get_setting("watch_auto", "false").lower() == "true"
    try:
        interval = int(database.get_setting("watch_interval_minutes", "360"))
    except ValueError:
        interval = 360
    if not enabled:
        return
    if monitor_progress["state"] == "running":
        return
    last = monitor_progress["started_at"]
    due = last is None or (dt.datetime.now() - dt.datetime.fromisoformat(last)).total_seconds() >= interval * 60
    if due:
        run_check()


def _loop() -> None:
    while not _stop.is_set():
        try:
            _tick()
        except Exception:  # noqa: BLE001 - 调度循环不能因单次异常退出
            pass
        _stop.wait(60)


def start() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, daemon=True)
    _thread.start()


def stop() -> None:
    _stop.set()
