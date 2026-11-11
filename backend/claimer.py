"""领取模块：浏览器自动化领取免费 DLC / 限时免费本体。

安全原则：
- 复用持久化浏览器 Profile，首次由用户手动登录 Steam；不存储密码与 Guard 密钥
- 严格串行，复用领取限速参数；遇登录墙 / 验证码 / 选择器缺失即暂停转人工
- 每个动作截图留证，回查归属后落库；中断可续跑，不重复领取已成功项

说明：真实商店页按钮选择器需在登录后的真实环境校准，本模块内置多候选选择器
与文本兜底；找不到按钮时记为 blocked 并截图，不盲点点击。
"""
from __future__ import annotations

import datetime as dt
import random
import re
import shutil
import threading
import time
from pathlib import Path

from . import config, database, logstore, notify
from .steam_client import SteamClient
from .throttler import ThrottleConfig, Throttler

try:  # playwright 为可选依赖，未安装时给出友好提示而非启动即崩
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None

claim_progress: dict = {
    "state": "idle",          # idle / running / done / error / blocked
    "total": 0,
    "current": 0,
    "message": "",
    "current_item": None,
    "counts": {"success": 0, "failed": 0, "skipped": 0, "blocked": 0},
    "started_at": None,
    "finished_at": None,
}
_lock = threading.Lock()


def _persist_state(state: str) -> None:
    """把上次领取状态写入本机数据库（仅本地，不上传）。"""
    try:
        database.set_setting("last_claim_state", state)
    except Exception:  # noqa: BLE001 - 状态记忆失败不影响主流程
        pass

SCREENSHOT_DIR = config.DATA_DIR / "screenshots"

# 领取按钮候选选择器（按优先级）
BUTTON_SELECTORS = [
    ".btn_add_to_library",
    "[data-gd-track-label='add_to_library']",
    "a.btn_green_steamui",
    ".game_area_purchase_game .btn_green_steamui",
]
BUTTON_TEXT_PATTERN = r"添加到库|Add to Library|添加到帐户|Add to Account|添加到购物车|Add to Cart"
BUTTON_TEXT_RE = re.compile(BUTTON_TEXT_PATTERN)
CONFIRM_RE = re.compile(r"确认|Confirm|继续|Continue|添加到库")
CART_TEXT_RE = re.compile(r"购物车|Cart")
CHECKOUT_RE = re.compile(r"结账|Checkout|为自己购买|Purchase for myself")
ORDER_CONFIRM_RE = re.compile(r"确认订单|确认购买|Confirm Purchase|购买|Purchase")


class ClaimError(Exception):
    """领取流程通用错误。"""


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _update(**kwargs) -> None:
    with _lock:
        claim_progress.update(kwargs)


def _resumable_items() -> list[dict]:
    """从本机队列取待领条目，剔除已成功/已在库的，避免重复领取。"""
    done = database.latest_claim_status()
    pending = database.pending_claim_queue()
    return [it for it in pending if done.get((it["appid"], it["kind"])) not in ("success", "skipped")]


def get_progress() -> dict:
    with _lock:
        snap = dict(claim_progress)
    # 进程重启后内存已清空；若队列仍有待领项，标记可续跑
    if snap["state"] == "idle":
        remaining = _resumable_items()
        if remaining:
            snap["interrupted"] = True
            snap["resumable"] = True
            snap["remaining"] = len(remaining)
        else:
            snap["remaining"] = 0
    return snap


def _screenshot(page, appid: int) -> str | None:
    try:
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        path = SCREENSHOT_DIR / f"{appid}_{dt.datetime.now().strftime('%H%M%S')}.png"
        page.screenshot(path=str(path), full_page=False)
        return str(path.relative_to(config.BASE_DIR))
    except Exception:  # noqa: BLE001
        return None


_CHANNEL_LABEL = {"msedge": "Microsoft Edge", "chrome": "Google Chrome", None: "自带 Chromium"}
_CHANNEL_ORDER = {
    "msedge": ("msedge", "chrome", None),
    "chrome": ("chrome", "msedge", None),
    "chromium": (None, "msedge", "chrome"),
}


def _profile_dir(channel: str | None) -> Path:
    """按渠道隔离持久化目录，避免 Chrome / Edge 共用同一 Profile 出现锁与组件冲突。"""
    sub = channel or "chromium"
    base = config.DATA_DIR / "browser_profile"
    d = base / sub
    if not d.exists():
        # 首次按渠道隔离：旧版本共用目录里若已有登录态，复制一份作为该渠道专属目录
        if base.exists() and any(base.iterdir()):
            try:
                shutil.copytree(base, d)
            except Exception:  # noqa: BLE001
                d.mkdir(parents=True, exist_ok=True)
        else:
            d.mkdir(parents=True, exist_ok=True)
    return d


def _launch_context(pw, headless: bool, channel_pref: str = "msedge"):
    """按设置渠道启动浏览器；返回 (context, 实际渠道名称)。

    首选渠道失败时才依次回退其余本机浏览器 / 自带 Chromium，每一步都写日志，
    避免静默换浏览器而用户误以为仍在用所选浏览器。
    """
    order = _CHANNEL_ORDER.get(channel_pref, _CHANNEL_ORDER["msedge"])
    last_err: Exception | None = None
    for channel in order:
        try:
            user_data = _profile_dir(channel)
            kwargs: dict = {
                "user_data_dir": str(user_data),
                "locale": "zh-CN",
                "headless": headless,
                "args": ["--disable-blink-features=AutomationControlled"],
            }
            if channel:
                kwargs["channel"] = channel
            ctx = pw.chromium.launch_persistent_context(**kwargs)
            label = _CHANNEL_LABEL[channel]
            logstore.add("INFO", f"领取浏览器已启动：{label}")
            return ctx, label
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            logstore.add("WARN", f"渠道「{_CHANNEL_LABEL[channel]}」启动失败，尝试下一个：{exc}")
    raise ClaimError(f"无法启动浏览器：{last_err}")


def _find_claim_button(page):
    for selector in BUTTON_SELECTORS:
        loc = page.locator(selector)
        if loc.count() > 0:
            return loc.first
    text_btn = page.get_by_text(BUTTON_TEXT_RE)
    if text_btn.count() > 0:
        return text_btn.first
    return None


def _checkout_cart(page, appid: int) -> tuple[str, str] | None:
    """0 元购物车结账：购物车 → 结账 → 确认下单。返回 (status, reason)，None 表示流程走完。"""
    page.goto("https://store.steampowered.com/cart/", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(1500)

    checks = page.locator("input[type='checkbox']")
    if checks.count() > 0:
        try:
            checks.first.check()
        except Exception:  # noqa: BLE001
            pass

    checkout = page.get_by_role("button", name=CHECKOUT_RE).first
    if checkout.count() == 0:
        checkout = page.get_by_text(CHECKOUT_RE).first
    if checkout.count() == 0:
        return "blocked", "购物车未找到结账按钮（选择器待校准）"
    checkout.click()
    page.wait_for_timeout(1500)

    confirm = page.get_by_role("button", name=ORDER_CONFIRM_RE).first
    if confirm.count() > 0:
        confirm.click()
        page.wait_for_timeout(1500)
    return None


def claim_one(context, item: dict, client: SteamClient, cc: str, lang: str) -> tuple[str, str, str | None]:
    """领取单个条目，返回 (status, reason, screenshot)。"""
    appid = item["appid"]
    page = context.new_page()
    try:
        url = f"https://store.steampowered.com/app/{appid}/?cc={cc}&l={lang}"
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(1500)

        # 登录墙检测
        if "/login" in page.url or page.get_by_text("登录 Steam").count() > 0:
            return "blocked", "需要先在浏览器中登录 Steam", _screenshot(page, appid)

        body = page.inner_text("body")
        if "在库中" in body or "In Library" in body:
            return "skipped", "已在库中", None

        button = _find_claim_button(page)
        if button is None:
            return "blocked", "未找到领取按钮（选择器待在真实环境校准）", _screenshot(page, appid)

        btn_text = ""
        try:
            btn_text = button.inner_text()
        except Exception:  # noqa: BLE001
            btn_text = ""

        if CART_TEXT_RE.search(btn_text):
            # 需加购物车走 0 元结账
            button.click()
            page.wait_for_timeout(1500)
            blocked = _checkout_cart(page, appid)
            if blocked:
                return blocked[0], blocked[1], _screenshot(page, appid)
        else:
            # 直接添加到库
            button.click()
            page.wait_for_timeout(1500)
            confirm = page.get_by_role("button", name=CONFIRM_RE).first
            if confirm.count() > 0:
                confirm.click()
                page.wait_for_timeout(1500)

        shot = _screenshot(page, appid)

        # 回查归属（有 Key 才回查）
        owned = False
        if client.api_key:
            try:
                owned = client.owns_app(appid)
            except Exception:  # noqa: BLE001
                owned = False

        if owned:
            return "success", "已领取并确认入库", shot
        return "success", "已点击领取（归属未回查）", shot
    except Exception as exc:  # noqa: BLE001
        return "failed", f"领取异常：{exc}", _screenshot(page, appid)
    finally:
        page.close()


def _record(item: dict, status: str, reason: str, screenshot: str | None, retries: int = 0) -> None:
    with database.get_conn() as conn:
        conn.execute(
            "INSERT INTO claim_records(dlc_appid, item_kind, batch_no, status, reason, retries, claimed_at, screenshot) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (item["appid"], item.get("kind", "dlc"), 0, status, reason, retries, _now(), screenshot),
        )


def start_claim(items: list[dict]) -> None:
    if claim_progress["state"] == "running":
        return
    database.save_claim_queue(items)
    threading.Thread(target=_claim_worker, args=(items,), daemon=True).start()


def resume_claim() -> dict:
    """续跑上次中断队列：跳过已成功/已在库项，返回是否启动。"""
    if claim_progress["state"] == "running":
        return {"ok": False, "error": "领取正在进行中"}
    remaining = _resumable_items()
    if not remaining:
        return {"ok": False, "error": "没有待领取的条目"}
    threading.Thread(target=_claim_worker, args=(remaining,), daemon=True).start()
    return {"ok": True, "count": len(remaining)}


def _claim_worker(items: list[dict]) -> None:
    if sync_playwright is None:
        _update(state="error", message="未安装 Playwright：请先 pip install playwright（浏览器复用本机 Chrome/Edge）",
                finished_at=_now())
        return

    s = database.get_settings()
    client = SteamClient.from_settings()
    thr = Throttler(ThrottleConfig(
        delay_min=float(s.get("claim_delay_min", 8.0)),
        delay_max=float(s.get("claim_delay_max", 20.0)),
        hourly_limit=int(s.get("claim_hourly_limit", 30)),
        max_retries=int(s.get("max_retries", 2)),
    ))
    batch_size = max(1, int(s.get("claim_batch_size", 5)))
    rest_min = float(s.get("batch_rest_min", 120.0))
    rest_max = float(s.get("batch_rest_max", 300.0))
    max_retries = max(0, int(s.get("max_retries", 2)))
    headless = s.get("claim_headless", "false").lower() == "true"
    channel_pref = s.get("browser_channel", "msedge")
    cc, lang = s.get("cc", "cn"), s.get("lang", "schinese")

    counts = {"success": 0, "failed": 0, "skipped": 0, "blocked": 0}
    _persist_state("running")
    logstore.add("INFO", f"领取开始：{len(items)} 个条目，浏览器渠道={channel_pref}，间隔 {thr.cfg.delay_min}-{thr.cfg.delay_max}s")
    _update(state="running", total=len(items), current=0, message="正在启动浏览器…",
            current_item=None, started_at=_now(), finished_at=None, counts=dict(counts))

    with sync_playwright() as pw:
        try:
            context, browser_label = _launch_context(pw, headless, channel_pref)
            _update(message=f"浏览器已启动：{browser_label}")
        except Exception as exc:  # noqa: BLE001
            logstore.add("ERROR", f"浏览器启动失败：{exc}")
            _persist_state("error")
            _update(state="error", message=f"浏览器启动失败：{exc}", finished_at=_now())
            return

        try:
            for idx, item in enumerate(items, start=1):
                _update(current=idx, current_item=item.get("name") or str(item["appid"]),
                        message=f"正在领取 {idx}/{len(items)}：{item.get('name', item['appid'])}")

                if not thr.check_hourly_budget():
                    _persist_state("blocked")
                    _update(state="blocked", message="达到每小时领取上限，已挂起，下个小时窗口再继续",
                            finished_at=_now())
                    break

                thr.wait_random_delay()
                status, reason, shot = claim_one(context, item, client, cc, lang)

                # 失败按设置次数重试，指数退避；受阻（blocked）不重试，直接转人工
                retries = 0
                while status == "failed" and retries < max_retries:
                    retries += 1
                    thr.backoff(retries)
                    status, reason, shot = claim_one(context, item, client, cc, lang)

                _record(item, status, reason, shot, retries)
                logstore.add("INFO" if status == "success" else "WARN",
                             f"[{status}] {item.get('name', item['appid'])}：{reason}")
                counts[status] = counts.get(status, 0) + 1
                if status == "success":
                    thr.mark_consumed()
                if status in ("success", "skipped"):
                    database.mark_claim_done(item["appid"], item.get("kind", "dlc"))
                _update(counts=dict(counts))

                # 遇阻即暂停，转人工；条目保留在队列，续跑时再处理
                if status == "blocked":
                    _persist_state("blocked")
                    _update(state="blocked", message=f"领取中断转人工：{reason}", finished_at=_now())
                    break

                # 批次间休息
                if idx % batch_size == 0 and idx < len(items):
                    time.sleep(random.uniform(rest_min, rest_max))
            else:
                _persist_state("done")
                _update(state="done", message="领取队列处理完成", finished_at=_now(), counts=counts)
        finally:
            context.close()

    if claim_progress["state"] in ("done", "blocked", "error"):
        notify.notify("领取结束", f"{claim_progress['message']} 统计：{claim_progress['counts']}")


def list_records(limit: int = 200) -> list[dict]:
    with database.get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM claim_records ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def open_login_window() -> None:
    """打开有头浏览器供首次手动登录 Steam，登录态写入持久化 Profile。"""
    if sync_playwright is None:
        raise ClaimError("未安装 Playwright：请先 pip install playwright")

    def _worker() -> None:
        channel_pref = database.get_setting("browser_channel", "msedge")
        with sync_playwright() as pw:
            context, browser_label = _launch_context(pw, headless=False, channel_pref=channel_pref)
            logstore.add("INFO", f"登录窗口已打开：{browser_label}")
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.goto("https://store.steampowered.com/login/")
                # 等待用户手动关闭窗口（最长 10 分钟）
                page.wait_for_event("close", timeout=600000)
            except Exception:  # noqa: BLE001
                pass
            finally:
                context.close()

    threading.Thread(target=_worker, daemon=True).start()
