"""库清理模块：按时长 / 从未玩过 / 下架状态筛选库内免费游戏。

安全设计：
- 默认排除付费购入，避免误删花钱买的游戏
- 收藏 / 忽略标记的条目不参与清理
- 先「干跑预览」出候选清单，人工勾选 + 二次确认后再执行移除
- 移除授权走本机浏览器登录态；真实页面选择器需在登录环境校准，
  本轮先落清单与记录，执行动作预留钩子，不盲点移除
- 所有数据仅存本机数据库，不上传
"""
from __future__ import annotations

import datetime as dt
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from fastapi import HTTPException

from . import database, logstore, scanner
from .steam_client import SteamClient

cleaner_progress: dict = {
    "state": "idle",          # idle / running / done / error
    "stage": "",
    "total": 0,
    "current": 0,
    "message": "",
    "counts": {},
    "started_at": None,
    "finished_at": None,
}
_lock = threading.Lock()


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _update(**kwargs) -> None:
    with _lock:
        cleaner_progress.update(kwargs)


def get_progress() -> dict:
    with _lock:
        return dict(cleaner_progress)


# ---------- 规则换算 ----------

def _to_minutes(value: float, unit: str) -> float:
    return value * 60.0 if unit == "hour" else float(value)


def _time_match(playtime_min: int, rule: dict) -> tuple[bool, str]:
    """判定时长是否命中规则；返回 (是否命中, 理由)。"""
    mode = rule.get("time_mode", "never")
    unit = rule.get("unit", "hour")
    if mode == "never":
        return playtime_min == 0, "从未游玩"
    try:
        t1 = _to_minutes(float(rule.get("threshold") or 0), unit)
    except ValueError:
        t1 = 0.0
    if mode == "lt":
        return playtime_min <= t1, f"时长 ≤ {rule.get('threshold')}{unit_label(unit)}"
    if mode == "gt":
        return playtime_min >= t1, f"时长 ≥ {rule.get('threshold')}{unit_label(unit)}"
    if mode == "range":
        try:
            t2 = _to_minutes(float(rule.get("threshold2") or 0), unit)
        except ValueError:
            t2 = t1
        lo, hi = sorted((t1, t2))
        return lo <= playtime_min <= hi, f"时长 {lo:.0f}–{hi:.0f} 分钟"
    return False, "未知时长规则"


def unit_label(unit: str) -> str:
    return " 小时" if unit == "hour" else " 分钟"


# ---------- 落库 ----------

def _upsert(item: dict) -> None:
    now = _now()
    with database.get_conn() as conn:
        conn.execute(
            "INSERT INTO cleaner_items(appid, name, playtime_forever, price_initial, price_final, "
            "app_type, delisted, status, reason, cover_url, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(appid) DO UPDATE SET name=excluded.name, playtime_forever=excluded.playtime_forever, "
            "price_initial=excluded.price_initial, price_final=excluded.price_final, "
            "app_type=excluded.app_type, delisted=excluded.delisted, status=excluded.status, "
            "reason=excluded.reason, cover_url=excluded.cover_url, fetched_at=excluded.fetched_at",
            (item["appid"], item["name"], item["playtime_forever"], item.get("price_initial"),
             item.get("price_final"), item.get("app_type"), item.get("delisted", 0),
             item["status"], item["reason"], item.get("cover_url"), now),
        )


def list_items(status: str | None = None) -> list[dict]:
    sql = "SELECT * FROM cleaner_items"
    args: list = []
    if status:
        sql += " WHERE status = ?"
        args.append(status)
    sql += " ORDER BY playtime_forever ASC, appid"
    with database.get_conn() as conn:
        rows = conn.execute(sql, args).fetchall()
    return [dict(r) for r in rows]


def mark_item(appid: int, field: str, value: int) -> None:
    if field not in ("favorite", "ignored"):
        raise HTTPException(status_code=400, detail="不支持的标记字段")
    with database.get_conn() as conn:
        conn.execute(f"UPDATE cleaner_items SET {field} = ? WHERE appid = ?", (value, appid))


def clear_items() -> None:
    with database.get_conn() as conn:
        conn.execute("DELETE FROM cleaner_items")


# ---------- 分析（干跑） ----------

def analyze(rule: dict) -> dict:
    with _lock:
        if cleaner_progress["state"] == "running":
            return {"ok": False, "error": "分析正在进行中"}
        cleaner_progress["state"] = "running"
    try:
        threading.Thread(target=_worker, args=(rule,), daemon=True).start()
    except Exception:
        _update(state="error", message="启动分析任务失败", finished_at=_now())
        raise
    return {"ok": True}


def _classify(details: dict | None, appid: int) -> dict:
    """Unknown store details are not proof of delisting or zero purchase price."""
    po = (details or {}).get("price_overview") or {}
    return {
        "delisted": 0,  # Requires independent evidence; no details may mean a network failure.
        "details_known": details is not None,
        "price_known": ("initial" in po or "initial_price" in po) and ("final" in po or "final_price" in po) or (details or {}).get("is_free") is True,
        "paid": bool(po and ((po.get("initial") or po.get("initial_price") or 0) > 0
                             or (po.get("final") or po.get("final_price") or 0) > 0)),
        "app_type": (details or {}).get("type", "") or "",
        "price_initial": po.get("initial", po.get("initial_price")),
        "price_final": po.get("final", po.get("final_price")),
        "cover": SteamClient.pick_cover(appid, (details or {}).get("header_image"), None),
    }


def _worker(rule: dict) -> None:
    _update(state="running", stage="连接账号", total=0, current=0,
            message="正在连接 Steam 账号…", started_at=_now(), finished_at=None, counts={})
    client = SteamClient.from_settings()
    thr = scanner._throttler_from_settings()

    try:
        games = client.get_owned_games()
    except Exception as exc:  # noqa: BLE001
        _update(state="error", message=f"拉取游戏库失败：{exc}", finished_at=_now())
        return

    total = len(games)
    logstore.add("INFO", f"库清理：库内 {total} 个游戏，开始读取详情并按规则筛选")
    _update(stage="读取详情", total=total, current=0, message=f"库内 {total} 个游戏，正在读取详情…")

    appids = [g["appid"] for g in games]
    details_map: dict[int, dict | None] = {}

    def on_progress(done: int, hit: bool) -> None:
        _update(current=done, message=f"读取详情 {done}/{total}")

    details_map, detail_failed = scanner._fetch_many(client, appids, thr, on_progress)
    if total and detail_failed == total:
        _update(state="error", message="游戏详情全部拉取失败，可能被网络或地区策略拦截，请稍后重试",
                finished_at=_now())
        return

    delisted_policy = rule.get("delisted", "exclude")   # keep / exclude / only
    include_paid = bool(rule.get("include_paid", False))

    counts = {"candidate": 0, "kept": 0}
    _update(stage="写入结果", current=total, total=total, message="正在按规则筛选…")

    for g in games:
        appid = g["appid"]
        details = details_map.get(appid)
        meta = _classify(details, appid)
        playtime = g.get("playtime_forever", 0) or 0

        # 收藏 / 忽略条目直接保留，不纳入候选
        existing = _existing_flags(appid)
        if existing.get("favorite") or existing.get("ignored"):
            status, reason = "kept", "已标记收藏/忽略，跳过"
        elif not meta["details_known"]:
            status, reason = "kept", "商店详情缺失不能确认价格或下架状态，安全排除"
        else:
            # Never treat a failed lookup or absent price as a confirmed free license.
            if not meta["price_known"] and not include_paid:
                status, reason = "kept", "价格未知，默认保护账号中的游戏"
            elif meta["paid"] and not include_paid:
                status, reason = "kept", "付费购入，默认排除（防误删）"
            elif delisted_policy == "only" and not meta["delisted"]:
                status, reason = "kept", "未能确认游戏已下架，按规则排除"
            elif meta["delisted"] and delisted_policy == "exclude":
                status, reason = "kept", "已下架/绝版，按规则排除"
            elif meta["delisted"] and delisted_policy == "only":
                hit, why = _time_match(playtime, rule)
                status, reason = ("candidate", f"已下架；{why}") if hit else ("kept", f"未命中时长规则（{why}）")
            else:
                hit, why = _time_match(playtime, rule)
                if hit:
                    status, reason = "candidate", why
                else:
                    status, reason = "kept", f"未命中时长规则（{why}）"

        item = {
            "appid": appid,
            "name": g.get("name", ""),
            "playtime_forever": playtime,
            "price_initial": meta["price_initial"],
            "price_final": meta["price_final"],
            "app_type": meta["app_type"],
            "delisted": meta["delisted"],
            "status": status,
            "reason": reason,
            "cover_url": meta["cover"],
        }
        _upsert(item)
        counts[status] = counts.get(status, 0) + 1

    logstore.add("INFO", f"库清理筛选完成：候选 {counts['candidate']}，保留 {counts['kept']}")
    _update(state="done", stage="完成", message=f"筛选完成：候选 {counts['candidate']} 个",
            finished_at=_now(), counts=counts)


def _existing_flags(appid: int) -> dict:
    with database.get_conn() as conn:
        row = conn.execute(
            "SELECT favorite, ignored FROM cleaner_items WHERE appid = ?", (appid,)
        ).fetchone()
    return {"favorite": row["favorite"] if row else 0, "ignored": row["ignored"] if row else 0}


# ---------- 移除（预留钩子） ----------

def remove_apps(appids: list[int]) -> dict:
    """批量移除授权。

    真实移除流程（账户许可证页 / 帮助页）的按钮选择器需在登录后的真实环境
    校准；本接口先记录移除意图与候选，执行动作待环境校准后接入，避免盲点。
    """
    if not appids:
        return {"ok": False, "error": "未选择要移除的游戏"}
    now = _now()
    with database.get_conn() as conn:
        for appid in appids:
            conn.execute(
                "INSERT INTO claim_records(dlc_appid, item_kind, batch_no, status, reason, retries, claimed_at, screenshot) "
                "VALUES (?, 'cleaner', 0, 'pending_remove', '待在真实环境校准移除流程', 0, ?, NULL)",
                (appid, now),
            )
            conn.execute(
                "UPDATE cleaner_items SET status = 'pending_remove' WHERE appid = ?", (appid,)
            )
    logstore.add("WARN", f"已登记 {len(appids)} 个待移除项；真实移除流程需在登录环境校准后接入")
    return {"ok": True, "count": len(appids),
            "note": "移除授权按钮选择器待登录环境校准，当前仅登记意图，未执行移除"}
