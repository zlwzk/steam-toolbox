"""创意工坊批量订阅 / 退订模块。

移植自原浏览器扩展：复用 Steam 原生 subscribe / unsubscribe 接口，
在 Playwright 页面上下文内发起 fetch（自动携带登录 Cookie），后端控制
拟人节奏、批次冷却、失败退避重试、自动翻页与中断续跑。

安全原则：
- 复用持久化浏览器 Profile，不读取或存储账号密码 / Guard
- 严格串行 + 随机间隔 + 批次冷却；429/5xx 指数退避，尊重 Retry-After
- 登录失效 / 选择器缺失即挂起转人工，不盲点
- 物品、状态、日志仅存本机数据库，不上传
"""
from __future__ import annotations

import datetime as dt
import random
import threading
import time

from fastapi import HTTPException

from . import claimer, config, database, logstore, notify
from .throttler import ThrottleConfig, Throttler

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None

ws_progress: dict = {
    "state": "idle",          # idle / running / paused / done / error / blocked
    "mode": "subscribe",
    "auto": False,
    "total": 0,
    "current": 0,
    "message": "",
    "current_item": None,
    "counts": {"success": 0, "failed": 0, "skipped": 0},
    "pages_done": 0,
    "started_at": None,
    "finished_at": None,
    "paused": False,
    "cancelled": False,
}
_lock = threading.Lock()


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _update(**kwargs) -> None:
    with _lock:
        ws_progress.update(kwargs)


def get_progress() -> dict:
    with _lock:
        return dict(ws_progress)


def _set_paused(v: bool) -> None:
    with _lock:
        ws_progress["paused"] = v


def _cancel() -> None:
    with _lock:
        ws_progress["cancelled"] = True
        ws_progress["paused"] = False


# ---------- 数据库 ----------

def _upsert_item(pid: int, appid: int, title: str, status: str, reason: str = "") -> None:
    now = _now()
    with database.get_conn() as conn:
        conn.execute(
            "INSERT INTO workshop_items(published_file_id, appid, title, status, reason, added_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(published_file_id) DO UPDATE SET "
            "title=excluded.title, status=excluded.status, reason=excluded.reason, updated_at=excluded.updated_at",
            (pid, appid, title, status, reason, now, now),
        )


def _record(item: dict, status: str, reason: str, retries: int = 0) -> None:
    with database.get_conn() as conn:
        conn.execute(
            "INSERT INTO claim_records(dlc_appid, item_kind, batch_no, status, reason, retries, claimed_at, screenshot) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (item["id"], "workshop", 0, status, reason, retries, _now(), None),
        )


def list_items(status: str | None = None) -> list[dict]:
    sql = "SELECT * FROM workshop_items"
    args: list = []
    if status:
        sql += " WHERE status = ?"
        args.append(status)
    sql += " ORDER BY updated_at DESC"
    with database.get_conn() as conn:
        rows = conn.execute(sql, args).fetchall()
    return [dict(r) for r in rows]


def mark_item(pid: int, field: str, value: int) -> None:
    if field not in ("favorite", "ignored"):
        raise HTTPException(status_code=400, detail="不支持的标记字段")
    with database.get_conn() as conn:
        conn.execute(f"UPDATE workshop_items SET {field} = ? WHERE published_file_id = ?", (value, pid))


def clear_items() -> None:
    with database.get_conn() as conn:
        conn.execute("DELETE FROM workshop_items")


# ---------- 页面脚本 ----------

SCAN_JS = r"""
() => {
  const seen = new Set();
  const items = [];
  for (const a of document.querySelectorAll('a[href*="sharedfiles/filedetails/?id="]')) {
    const m = a.href.match(/filedetails\/\?id=(\d+)/);
    if (!m) continue;
    const id = m[1];
    if (seen.has(id)) continue;
    seen.add(id);
    const img = a.querySelector('img');
    const title = (img && img.alt) || a.textContent.trim() || id;
    items.push({ id, title });
  }
  return items;
}
"""

ACTION_JS = r"""
async ({ id, appid, action }) => {
  const sessionid = (document.cookie.match(/(?:^|;\s*)sessionid=([^;]+)/) || [])[1] || '';
  const endpoint = action === 'unsubscribe'
    ? 'https://steamcommunity.com/sharedfiles/unsubscribe'
    : 'https://steamcommunity.com/sharedfiles/subscribe';
  const body = new URLSearchParams({ id, appid: appid || '', sessionid }).toString();
  const resp = await fetch(endpoint, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8' },
    body,
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

def _sleep_interruptible(seconds: float) -> bool:
    """每 200ms 检查暂停 / 取消；返回 False 表示已取消。"""
    waited = 0.0
    while waited < seconds:
        if ws_progress["cancelled"]:
            return False
        if ws_progress["paused"]:
            time.sleep(0.3)
            continue
        time.sleep(min(0.2, seconds - waited))
        waited += 0.2
    return not ws_progress["cancelled"]


def _cooldown(total_sec: float) -> bool:
    remain = max(1, round(total_sec))
    while remain > 0:
        _update(message=f"批次冷却 {remain} 秒")
        if not _sleep_interruptible(1):
            return False
        remain -= 1
    return True


def _browse_url(appid: str, page_no: int) -> str:
    return f"https://steamcommunity.com/workshop/browse/?appid={appid}&p={page_no}"


def _action_one(page, item: dict, appid: str, action: str) -> tuple[str, str]:
    """在页面上下文内调用订阅接口，返回 (status, reason)。"""
    res = page.evaluate(ACTION_JS, {"id": str(item["id"]), "appid": appid, "action": action})
    if res.get("redirected") or res.get("isHtml"):
        return "blocked", "登录态失效，请重新登录 Steam"
    if res.get("status") == 429 or (res.get("status") or 0) >= 500:
        raise claimer.ClaimError(f"http {res['status']}")
    if res.get("success"):
        return "success", "操作成功"
    return "failed", "Steam 返回未成功"


def start_task(appid: str, mode: str = "subscribe", auto: bool = False,
               range_start: int = 0, range_end: int = 0) -> dict:
    if ws_progress["state"] == "running":
        return {"ok": False, "error": "工坊任务正在进行中"}
    appid = str(appid).strip()
    if not appid.isdecimal() or len(appid) > 12 or int(appid) < 1:
        return {"ok": False, "error": "请填写有效的游戏 AppID"}
    if mode not in ("subscribe", "unsubscribe"):
        return {"ok": False, "error": "只支持订阅或退订"}
    if range_start < 0 or range_end < 0 or (range_start and range_end and range_end < range_start):
        return {"ok": False, "error": "序号范围无效"}
    s = database.get_settings()
    if not (s.get("api_key") and s.get("steamid")):
        return {"ok": False, "error": "请先在「账号绑定」填入 API Key 与 SteamID，并在弹出浏览器完成 Steam 登录"}
    ws_progress.update({
        "state": "running", "mode": mode, "auto": auto, "total": 0, "current": 0,
        "message": "正在启动浏览器…", "current_item": None,
        "counts": {"success": 0, "failed": 0, "skipped": 0}, "pages_done": 0,
        "started_at": _now(), "finished_at": None, "paused": False, "cancelled": False,
    })
    threading.Thread(target=_worker, args=(appid, mode, auto, range_start, range_end),
                     daemon=True).start()
    return {"ok": True}


def pause_task() -> dict:
    if ws_progress["state"] != "running":
        return {"ok": False, "error": "当前没有运行中的任务"}
    _set_paused(not ws_progress["paused"])
    return {"ok": True, "paused": ws_progress["paused"]}


def cancel_task() -> dict:
    if ws_progress["state"] not in ("running", "paused"):
        return {"ok": False, "error": "当前没有运行中的任务"}
    _cancel()
    return {"ok": True}


def _worker(appid: str, mode: str, auto: bool, range_start: int, range_end: int) -> None:
    if sync_playwright is None:
        _update(state="error", message="未安装 Playwright", finished_at=_now())
        return

    s = database.get_settings()
    thr = Throttler(ThrottleConfig(
        delay_min=float(s.get("ws_delay_min", 2.5)),
        delay_max=float(s.get("ws_delay_max", 5.0)),
        max_retries=int(s.get("ws_max_retries", 3)),
    ))
    batch_size = max(1, int(s.get("ws_batch_size", 10)))
    cooldown_enabled = s.get("ws_cooldown_enabled", "true").lower() == "true"
    cd_min = float(s.get("ws_cooldown_min", 20))
    cd_max = float(s.get("ws_cooldown_max", 45))
    max_retries = max(0, int(s.get("ws_max_retries", 3)))
    max_pages = max(1, min(100, int(s.get("ws_max_pages", 20))))
    headless = s.get("claim_headless", "false").lower() == "true"
    channel_pref = s.get("browser_channel", "msedge")

    counts = {"success": 0, "failed": 0, "skipped": 0}
    last_failed: list[dict] = []
    logstore.add("INFO", f"工坊任务开始：mode={mode}，自动翻页={auto}，AppID={appid}")

    with sync_playwright() as pw:
        try:
            context, browser_label, _real_key = claimer._launch_context(pw, headless, channel_pref)
            _update(message=f"浏览器已启动：{browser_label}")
        except Exception as exc:  # noqa: BLE001
            logstore.add("ERROR", f"浏览器启动失败：{exc}")
            _update(state="error", message=f"浏览器启动失败：{exc}", finished_at=_now())
            return

        try:
            page = context.pages[0] if context.pages else context.new_page()
            page_no = 1
            first_id_seen: str | None = None

            while True:
                page.goto(_browse_url(appid, page_no), wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(1500)

                if "/login" in page.url:
                    _update(state="blocked", message="需要先在浏览器中登录 Steam", finished_at=_now())
                    logstore.add("WARN", "工坊：登录态失效，转人工")
                    return

                items = page.evaluate(SCAN_JS)
                if not items:
                    logstore.add("INFO", f"第 {page_no} 页无物品，任务结束")
                    break

                # 重复页守卫：越界页码被钳制回末页，首项与上页相同即停止
                if auto and first_id_seen and items[0]["id"] == first_id_seen:
                    logstore.add("INFO", "已到末页（重复页守卫）")
                    break
                first_id_seen = items[0]["id"]

                # 序号范围（仅作用于起始页）
                if page_no == 1 and (range_start > 0 or range_end > 0):
                    a = range_start > 0 and range_start or 1
                    b = range_end > 0 and range_end or len(items)
                    a = max(1, min(a, len(items)))
                    b = max(1, min(b, len(items)))
                    if a > b:
                        a, b = b, a
                    items = items[a - 1:b]

                _update(total=ws_progress["total"] + len(items),
                        pages_done=page_no, message=f"第 {page_no} 页：{len(items)} 个物品")

                since_batch = 0
                for idx, item in enumerate(items, start=1):
                    if ws_progress["cancelled"]:
                        break

                    thr.wait_random_delay()
                    _update(current=ws_progress["current"] + 1,
                            current_item=item["title"],
                            message=f"[{page_no} 页 {idx}/{len(items)}] {item['title']}")

                    status, reason = "failed", ""
                    retries = 0
                    for attempt in range(max_retries + 1):
                        try:
                            status, reason = _action_one(page, item, appid, mode)
                            break
                        except claimer.ClaimError as exc:
                            if attempt >= max_retries:
                                reason = str(exc)
                                break
                            retries = attempt + 1
                            wait = min(30 * (2 ** attempt), 300)
                            logstore.add("INFO", f"限流退避 {wait}s：{item['title']}")
                            if not _sleep_interruptible(wait):
                                break
                        except Exception as exc:  # noqa: BLE001
                            status, reason = "failed", f"异常：{exc}"
                            break

                    if status == "blocked":
                        _update(state="blocked", message=reason, finished_at=_now())
                        _record(item, status, reason, retries)
                        return

                    _upsert_item(int(item["id"]), int(appid), item["title"], status, reason)
                    _record(item, status, reason, retries)
                    counts[status] = counts.get(status, 0) + 1
                    if status == "failed":
                        last_failed.append(item)
                    logstore.add("INFO" if status == "success" else "WARN",
                                 f"[{status}] {item['title']}：{reason}")
                    _update(counts=dict(counts))

                    since_batch += 1
                    if cooldown_enabled and since_batch >= batch_size and idx < len(items):
                        since_batch = 0
                        cd = round(random.uniform(cd_min, cd_max))
                        logstore.add("INFO", f"批次冷却 {cd}s")
                        if not _cooldown(cd):
                            break

                if ws_progress["cancelled"]:
                    break

                if not auto:
                    break
                if page_no >= max_pages:
                    logstore.add("INFO", f"达到翻页上限 {max_pages} 页")
                    break
                page_no += 1

            final_state = "cancelled" if ws_progress["cancelled"] else "done"
            _update(state=final_state, message="工坊任务结束", finished_at=_now(), counts=counts)
            logstore.add("INFO", f"工坊任务完成：成功 {counts['success']}，失败 {counts['failed']}")
        finally:
            context.close()

    if ws_progress["state"] in ("done", "blocked", "error"):
        notify.notify("工坊任务结束", f"{ws_progress['message']} 统计：{ws_progress['counts']}")


def retry_failed() -> dict:
    """精准重试失败项。"""
    if ws_progress["state"] == "running":
        return {"ok": False, "error": "任务进行中"}
    failed = [it for it in list_items("failed")]
    if not failed:
        return {"ok": False, "error": "没有失败项可重试"}
    # 以首个失败项所在 appid 重启；失败项跨游戏时按记录 appid 分组由前端确认
    appid = str(failed[0]["appid"])
    threading.Thread(target=_retry_worker, args=(failed, appid), daemon=True).start()
    return {"ok": True, "count": len(failed)}


def _retry_worker(items: list[dict], appid: str) -> None:
    if sync_playwright is None:
        _update(state="error", message="未安装 Playwright", finished_at=_now())
        return
    s = database.get_settings()
    thr = Throttler(ThrottleConfig(
        delay_min=float(s.get("ws_delay_min", 2.5)),
        delay_max=float(s.get("ws_delay_max", 5.0)),
    ))
    mode = ws_progress["mode"]
    ws_progress.update({"state": "running", "total": len(items), "current": 0,
                         "counts": {"success": 0, "failed": 0, "skipped": 0},
                         "started_at": _now(), "finished_at": None, "cancelled": False})
    with sync_playwright() as pw:
        try:
            context, _, _real_key = claimer._launch_context(pw, s.get("claim_headless", "false") == "true",
                                                  s.get("browser_channel", "msedge"))
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(_browse_url(appid, 1), wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(1200)
            for i, it in enumerate(items, start=1):
                if ws_progress["cancelled"]:
                    break
                thr.wait_random_delay()
                item = {"id": str(it["published_file_id"]), "title": it["title"]}
                status, reason = _action_one(page, item, appid, mode)
                _upsert_item(it["published_file_id"], it["appid"], it["title"], status, reason)
                _record(item, status, reason)
                ws_progress["counts"][status] = ws_progress["counts"].get(status, 0) + 1
                _update(current=i)
            _update(state="done", message="失败项重试完成", finished_at=_now())
        except Exception as exc:  # noqa: BLE001
            _update(state="error", message=f"重试异常：{exc}", finished_at=_now())
        finally:
            context.close()
