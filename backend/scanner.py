"""盘点与判定：DLC 扫描 + 喜加一（限时免费本体）扫描。

DLC 状态：claimable / owned / skipped / unknown
本体状态：limited_free（限时免费喜加一）/ permanent_free（永久免费 F2P，不领）/
         paid / demo / unknown
"""
from __future__ import annotations

import datetime as dt
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import config, database, logstore, notify
from .steam_client import RateLimited, SteamApiError, SteamClient, StoreBlocked
from .throttler import ThrottleConfig, Throttler

progress: dict = {
    "state": "idle",
    "kind": "dlc",
    "stage": "",
    "total": 0,
    "current": 0,
    "cached": 0,
    "message": "",
    "started_at": None,
    "finished_at": None,
    "counts": {},
}
_lock = threading.Lock()
# 暂停/继续：event set=运行，clear=暂停；worker 在断点处 wait 挂起，不丢弃已拉结果
_pause_event = threading.Event()
_pause_event.set()


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _update(**kwargs) -> None:
    with _lock:
        progress.update(kwargs)


def get_progress() -> dict:
    with _lock:
        snap = dict(progress)
    # 进程重启后内存状态已清空；若上次退出时仍在跑/暂停，标记为可继续（走缓存增量续扫）
    if snap["state"] == "idle":
        last_state = database.get_setting("last_scan_state", "")
        last_kind = database.get_setting("last_scan_kind", "")
        if last_state in ("running", "paused"):
            snap["interrupted"] = True
            snap["interrupted_kind"] = last_kind or "dlc"
            snap["resumable"] = True
    return snap


def _persist_state(state: str, kind: str | None = None) -> None:
    """把上次扫描状态/范围写入本机数据库（仅本地，不上传）。"""
    try:
        database.set_setting("last_scan_state", state)
        if kind is not None:
            database.set_setting("last_scan_kind", kind)
    except Exception:  # noqa: BLE001 - 状态记忆失败不影响主流程
        pass


def pause_scan() -> bool:
    """请求暂停：worker 到达下一个断点挂起；状态立即置为暂停以便前端显示。"""
    with _lock:
        if progress["state"] != "running":
            return False
        _pause_event.clear()
        progress.update(state="paused", message="已暂停，等待继续…")
        kind = progress.get("kind")
    _persist_state("paused", kind)
    return True


def resume_scan() -> bool:
    """继续扫描：解除挂起。仅暂停态可继续。"""
    with _lock:
        if progress["state"] != "paused":
            return False
        _pause_event.set()
        progress.update(state="running", message="继续扫描…")
    return True


def _check_pause() -> None:
    """断点检查：被暂停则挂起等待继续，已拉取结果保留在内存中不重拉。"""
    if _pause_event.is_set():
        return
    _update(state="paused", message="已暂停，等待继续…")
    _persist_state("paused", progress.get("kind"))
    _pause_event.wait()
    _update(state="running", message="继续扫描…")


# ---------- 判定规则 ----------

def evaluate_dlc(data: dict | None, parent_appids: list[int] | set[int],
                 owned_appids: set[int]) -> tuple[str, str]:
    """R1-R7 DLC 判定，返回 (status, reason)。

    同一 DLC 可能挂在多个本体下，parent_appids 为其全部挂载本体；只要其中
    任一本体已拥有，即视为归属成立，避免重复条目被误判为「本体未拥有」。
    """
    if not data:
        return "unknown", "商店数据缺失，待人工确认"

    app_type = (data.get("type") or "").lower()
    if app_type == "bundle":
        return "skipped", "捆绑包/合集包，非独立 DLC"
    if app_type != "dlc":
        return "skipped", f"类型为 {app_type or '未知'}，非 DLC"

    po = data.get("price_overview")
    if po is None:
        pass
    else:
        initial = po.get("initial", po.get("initial_price", 0)) or 0
        final = po.get("final", po.get("final_price", 0)) or 0
        if final == 0 and initial > 0:
            return "skipped", "限时 -100% 折扣，非永久免费"
        if final > 0:
            currency = po.get("currency", "")
            return "skipped", f"付费 DLC（{currency} {final}）"

    if not any(p in owned_appids for p in parent_appids):
        return "skipped", "本体未拥有"

    if (not po or not ({"initial", "final"} <= set(po) or {"initial_price", "final_price"} <= set(po))) and data.get("is_free") is not True:
        return "unknown", "无价格信息，需人工确认是否免费"
    return "claimable", "免费 DLC，可领取"


def evaluate_game(data: dict | None, owned: bool = False) -> tuple[str, str]:
    """本体判定：只把「原付费、现限时 0 元」的喜加一列为可领，永久免费 F2P 排除。"""
    if owned:
        return "owned", "已在库中，不再显示"
    if not data:
        return "unknown", "商店数据缺失，待人工确认"

    app_type = (data.get("type") or "").lower()
    if app_type == "demo":
        return "demo", "试玩 Demo，非完整游戏"

    po = data.get("price_overview")
    if not po or not ({"initial", "final"} <= set(po) or {"initial_price", "final_price"} <= set(po)):
        return ("permanent_free", "永久免费（F2P），不领取") if data.get("is_free") is True else ("unknown", "缺少价格信息，待确认")

    initial = po.get("initial", po.get("initial_price", 0)) or 0
    final = po.get("final", po.get("final_price", 0)) or 0
    if final > 0:
        return "paid", f"付费游戏（{po.get('currency', '')} {final}）"
    if initial > 0 and final == 0:
        return "limited_free", "限时免费喜加一，可领取"
    return "permanent_free", "永久免费（F2P），不领取"


# ---------- 落库 ----------

def _upsert_owned(games: list[dict]) -> set[int]:
    owned: set[int] = set()
    now = _now()
    with database.get_conn() as conn:
        for g in games:
            appid = g["appid"]
            owned.add(appid)
            conn.execute(
                "INSERT INTO owned_games(appid, name, playtime_forever, last_synced_at) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(appid) DO UPDATE SET name = excluded.name, "
                "playtime_forever = excluded.playtime_forever, last_synced_at = excluded.last_synced_at",
                (appid, g.get("name", ""), g.get("playtime_forever", 0), now),
            )
    return owned


def _save_dlc(dlc_appid: int, parent_appid: int, data: dict | None, status: str, reason: str) -> None:
    now = _now()
    po = (data or {}).get("price_overview") or {}
    cover = SteamClient.pick_cover(dlc_appid, (data or {}).get("header_image"), None)
    with database.get_conn() as conn:
        conn.execute(
            "INSERT INTO dlc_items(dlc_appid, parent_appid, name, type, price_initial, price_final, "
            "currency, cc, supported_languages, review_score, cover_url, header_image, owned, raw_json, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(dlc_appid) DO UPDATE SET parent_appid = excluded.parent_appid, "
            "name = excluded.name, type = excluded.type, price_initial = excluded.price_initial, "
            "price_final = excluded.price_final, currency = excluded.currency, cc = excluded.cc, "
            "supported_languages = excluded.supported_languages, review_score = excluded.review_score, "
            "cover_url = excluded.cover_url, header_image = excluded.header_image, "
            "raw_json = excluded.raw_json, fetched_at = excluded.fetched_at",
            (
                dlc_appid,
                parent_appid,
                (data or {}).get("name", ""),
                (data or {}).get("type", ""),
                po.get("initial", po.get("initial_price")),
                po.get("final", po.get("final_price")),
                po.get("currency"),
                (data or {}).get("price_overview", {}).get("cc"),
                str((data or {}).get("supported_languages", "")),
                None,
                cover,
                (data or {}).get("header_image"),
                0,
                json.dumps(data, ensure_ascii=False) if data else None,
                now,
            ),
        )
        conn.execute(
            "INSERT INTO candidates(dlc_appid, item_type, status, reason, cover_url, added_at, updated_at) "
            "VALUES (?, 'dlc', ?, ?, ?, ?, ?) "
            "ON CONFLICT(dlc_appid) DO UPDATE SET status = excluded.status, reason = excluded.reason, "
            "cover_url = excluded.cover_url, updated_at = excluded.updated_at",
            (dlc_appid, status, reason, cover, now, now),
        )


def _save_free_game(item: dict, data: dict | None, status: str, reason: str) -> None:
    now = _now()
    appid = item["appid"]
    po = (data or {}).get("price_overview") or {}
    cover = SteamClient.pick_cover(appid, (data or {}).get("header_image"), item.get("logo"))
    desc = ((data or {}).get("short_description") or "")[:300]
    with database.get_conn() as conn:
        conn.execute(
            "INSERT INTO free_games(appid, name, cover_url, header_image, type, price_initial, price_final, "
            "currency, discount_percent, supported_languages, review_score, description, status, reason, "
            "fetched_at, added_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(appid) DO UPDATE SET name = excluded.name, cover_url = excluded.cover_url, "
            "header_image = excluded.header_image, type = excluded.type, price_initial = excluded.price_initial, "
            "price_final = excluded.price_final, currency = excluded.currency, "
            "discount_percent = excluded.discount_percent, supported_languages = excluded.supported_languages, "
            "review_score = excluded.review_score, description = excluded.description, status = excluded.status, "
            "reason = excluded.reason, fetched_at = excluded.fetched_at",
            (
                appid,
                (data or {}).get("name") or item.get("name", ""),
                cover,
                (data or {}).get("header_image"),
                (data or {}).get("type", ""),
                po.get("initial", po.get("initial_price")),
                po.get("final", po.get("final_price")),
                po.get("currency"),
                po.get("discount_percent"),
                str((data or {}).get("supported_languages", "")),
                None,
                desc,
                status,
                reason,
                now,
                now,
            ),
        )


# ---------- 扫描调度 ----------

def run_scan(kind: str = "dlc", force: bool = False) -> bool:
    """Start once even when the UI submits multiple requests quickly."""
    with _lock:
        if progress["state"] in ("running", "paused"):
            return False
        progress["state"] = "running"
    try:
        if force:
            database.clear_cache()
        _pause_event.set()
        _persist_state("running", kind)
        threading.Thread(target=_scan_worker, args=(kind,), daemon=True).start()
    except Exception:
        _update(state="error", message="启动扫描失败", finished_at=_now())
        raise
    return True


def get_overview() -> dict:
    return database.scan_overview()


def _throttler_from_settings() -> Throttler:
    s = database.get_settings()
    return Throttler(ThrottleConfig(
        delay_min=float(s.get("fetch_delay_min", config.FETCH_DELAY_MIN)),
        delay_max=float(s.get("fetch_delay_max", config.FETCH_DELAY_MAX)),
        max_retries=int(s.get("max_retries", 2)),
    ))


def _concurrency() -> int:
    try:
        n = int(database.get_setting("fetch_concurrency") or config.FETCH_CONCURRENCY)
    except ValueError:
        n = config.FETCH_CONCURRENCY
    return max(1, min(5, n))


def _fetch_many(client: SteamClient, appids: list[int], thr: Throttler,
                on_progress) -> tuple[dict[int, dict | None], int]:
    """分批并发拉取详情：每批合并为一次 appdetails 请求，减少往返。

    返回 ({appid: details|None}, 失败条数)。所有传入 appid 都会出现在结果中：
    - 单条无数据/解析失败隔离为 None，交由判定层归为「待确认」；
    - 整批被商店拦截（StoreBlocked，403/拦截页）计入熔断，连续多批被拦即中断，
      不再逐条慢速重试把清单全部标成未知；
    - 限流 429 属于全局信号，仍向上抛出由顶层退避处理。
    """
    uniq = list(dict.fromkeys(appids))
    results: dict[int, dict | None] = {}
    if not uniq:
        return results, 0

    batch_size = config.APPDETAILS_BATCH_SIZE
    blocks = [uniq[i:i + batch_size] for i in range(0, len(uniq), batch_size)]
    blocked_blocks = 0
    BLOCK_BLOCK_LIMIT = 2  # 连续被拦批次达到该值即判定出口被整体拦截，快速熔断

    def fetch_block(chunk: list[int]):
        try:
            # 全局节奏闸门：并发线程在此串行化请求发出时刻，避免扎堆触发限流
            thr.gate()
            batch = client.get_appdetails_batch(chunk)
            return chunk, batch, client.last_cache_hit, None
        except StoreBlocked as exc:
            return chunk, None, False, ("blocked", str(exc))
        except RateLimited:
            raise  # 限流需全局退避，不在批次层隔离
        except SteamApiError as exc:
            return chunk, None, False, ("err", str(exc))
        except Exception as exc:  # noqa: BLE001 - 单批异常隔离，避免整批中断
            return chunk, None, False, ("err", f"详情拉取异常：{exc}")

    done = 0
    failed = 0
    blocked = 0
    with ThreadPoolExecutor(max_workers=_concurrency()) as ex:
        futs = [ex.submit(fetch_block, b) for b in blocks]
        for fut in as_completed(futs):
            chunk, batch, hit, err = fut.result()
            if err and err[0] == "blocked":
                blocked_blocks += 1
                blocked += len(chunk)
                logstore.add("WARN", f"批次 {chunk[0]}… 被商店拦截：{err[1]}")
                for aid in chunk:
                    results.setdefault(aid, None)
                if blocked_blocks >= BLOCK_BLOCK_LIMIT:
                    for f in futs:
                        f.cancel()
                    raise StoreBlocked(err[1])
            else:
                blocked_blocks = 0
                if err:
                    failed += len(chunk)
                    for aid in chunk:
                        results.setdefault(aid, None)
                    logstore.add("WARN", f"批次 {chunk[0]}… 详情拉取失败：{err[1]}")
                else:
                    for aid, body in (batch or {}).items():
                        results[aid] = body
            done += len(chunk)
            on_progress(done, hit)
            _check_pause()

    if failed:
        logstore.add("WARN", f"共 {failed}/{len(uniq)} 条详情拉取失败，已标记为待确认")
    if blocked:
        logstore.add("WARN", f"{blocked} 条因商店接口被拦截而缺失详情")
    return results, failed


def _scan_worker(kind: str) -> None:
    counts: dict = {}
    _update(state="running", kind=kind, stage="连接账号", total=0, current=0, cached=0,
            message="正在连接 Steam 账号…", started_at=_now(), finished_at=None, counts=counts)
    client = SteamClient.from_settings()
    thr = _throttler_from_settings()

    rounds = max(1, thr.cfg.max_retries + 1)
    limited: RateLimited | None = None

    for round_no in range(rounds):
        try:
            if kind == "freegame":
                _scan_free_games(client, thr)
            else:
                _scan_dlc(client, thr)
            limited = None
            break
        except RateLimited as exc:
            limited = exc
            if round_no >= rounds - 1:
                break
            wait = thr.backoff(round_no, exc.retry_after)
            logstore.add("WARN", f"被 Steam 限流，退避 {wait:.0f}s 后自动续扫（第 {round_no + 1}/{rounds} 轮）")
            _update(state="running", message=f"被限流，退避 {wait:.0f}s 后自动续扫…")
        except StoreBlocked as exc:
            _update(state="error", message=f"商店接口被拦截：{exc}", finished_at=_now())
            _persist_state("error", kind)
            notify.notify("盘点失败", f"[{kind}] {progress['message']}")
            return
        except SteamApiError as exc:
            _update(state="error", message=f"账号/接口错误：{exc}", finished_at=_now())
            _persist_state("error", kind)
            notify.notify("盘点失败", f"[{kind}] {progress['message']}")
            return
        except Exception as exc:  # noqa: BLE001 - 顶层兜底，落库为错误状态
            _update(state="error", message=f"扫描异常：{exc}", finished_at=_now())
            _persist_state("error", kind)
            notify.notify("盘点失败", f"[{kind}] {progress['message']}")
            return

    if limited is not None:
        _update(state="error", message="被 Steam 限流，多次退避后仍中断，请稍后手动重试",
                finished_at=_now())
        _persist_state("error", kind)
        notify.notify("盘点失败", f"[{kind}] {progress['message']}")
        return

    if progress["state"] == "done":
        _persist_state("done", kind)
        notify.notify("盘点完成", f"[{kind}] {progress['message']} 统计：{progress['counts']}")
    elif progress["state"] == "error":
        _persist_state("error", kind)
        notify.notify("盘点失败", f"[{kind}] {progress['message']}")


def _scan_dlc(client: SteamClient, thr: Throttler) -> None:
    games = client.get_owned_games()
    owned_appids = _upsert_owned(games)
    n_games = len(games)
    logstore.add("INFO", f"DLC 扫描：库内本体 {n_games} 个，并发 {_concurrency()} 拉取详情")

    # 阶段一：并发读取本体详情，收集各自携带的 DLC 清单
    _update(stage="读取本体清单", total=n_games, current=0, cached=0,
            message=f"库内本体 {n_games} 个，正在读取 DLC 清单…")
    cached = [0]

    def on_parent(done: int, hit: bool) -> None:
        if hit:
            cached[0] += 1
        _update(current=done, cached=cached[0],
                message=f"读取本体 {done}/{n_games}")

    parent_ids = [g["appid"] for g in games]
    parent_map, parent_failed = _fetch_many(client, parent_ids, thr, on_parent)

    # 本体详情全部拉取失败：属账号/网络/地区级问题，按错误中断并提示，不假装盘点完成
    if n_games and parent_failed == n_games:
        raise SteamApiError("本体详情全部拉取失败，可能被网络或地区策略拦截，请稍后重试")

    # 按 DLC 去重聚合挂载本体；同一 DLC 挂多个本体时只拉一次、只落库一次
    parents_of: dict[int, list[int]] = {}
    for g in games:
        details = parent_map.get(g["appid"])
        for dlc_id in (details or {}).get("dlc", []) or []:
            parents_of.setdefault(int(dlc_id), []).append(g["appid"])

    # 阶段二：并发拉取 DLC 详情，主线程串行判定落库
    dlc_ids = list(parents_of.keys())
    total = len(dlc_ids)
    _update(stage="判定 DLC", total=total, current=0,
            message=f"共发现 {total} 个 DLC，开始逐条判定…")

    def on_dlc(done: int, hit: bool) -> None:
        if hit:
            cached[0] += 1
        _update(current=done, cached=cached[0], message=f"拉取 DLC 详情 {done}/{total}")

    dlc_map, dlc_failed = _fetch_many(client, dlc_ids, thr, on_dlc)
    if total and dlc_failed == total:
        raise SteamApiError("DLC 详情全部拉取失败，可能被网络或地区策略拦截，请稍后重试")

    counts = {"claimable": 0, "owned": 0, "skipped": 0, "unknown": 0}
    _update(stage="写入结果", current=total, total=total, message="正在写入判定结果…")
    for idx, dlc_appid in enumerate(dlc_ids, start=1):
        parents = parents_of[dlc_appid]
        details = dlc_map.get(dlc_appid)
        status, reason = evaluate_dlc(details, parents, owned_appids)
        _save_dlc(dlc_appid, parents[0], details, status, reason)
        counts[status] = counts.get(status, 0) + 1
        _check_pause()
        if idx % 20 == 0 or idx == total:
            _update(current=idx, cached=cached[0], counts=dict(counts),
                    message=f"写入结果 {idx}/{total}")

    fail_note = f"；{dlc_failed} 条详情失败已标记待确认" if dlc_failed else ""
    logstore.add("INFO", f"DLC 盘点完成：{counts}")
    _update(state="done", stage="完成", message=f"DLC 盘点完成{fail_note}",
            finished_at=_now(), counts=counts)


def _scan_free_games(client: SteamClient, thr: Throttler) -> None:
    s = database.get_settings()
    try:
        pages = max(1, int(s.get("free_game_pages", 2)))
    except ValueError:
        pages = 2

    # 拉取库内已有本体用于过滤已拥有项；缺 Key/网络失败时降级为空集，不阻断商店扫描
    owned_appids: set[int] = set()
    try:
        owned_appids = _upsert_owned(client.get_owned_games())
    except Exception as exc:  # noqa: BLE001
        logstore.add("WARN", f"未能拉取库内游戏，已拥有项暂不过滤：{exc}")

    _update(stage="检索商店", total=1, current=0, message="正在检索商店免费列表…")
    items = client.search_free_games(pages=pages, count=50)
    total = len(items)
    _update(stage="核定价格", total=total, current=0,
            message=f"商店免费列表 {total} 个，正在核定是否限时免费…")
    counts = {"limited_free": 0, "permanent_free": 0, "paid": 0, "demo": 0, "unknown": 0, "owned": 0}
    cached = [0]

    def on_item(done: int, hit: bool) -> None:
        if hit:
            cached[0] += 1
        _update(current=done, cached=cached[0], message=f"核定价格 {done}/{total}")

    details_map, detail_failed = _fetch_many(client, [i["appid"] for i in items], thr, on_item)
    if total and detail_failed == total:
        raise SteamApiError("喜加一详情全部拉取失败，可能被网络或地区策略拦截，请稍后重试")

    _update(stage="写入结果", current=total, total=total, message="正在写入判定结果…")
    for idx, item in enumerate(items, start=1):
        details = details_map.get(item["appid"])
        status, reason = evaluate_game(details, item["appid"] in owned_appids)
        _save_free_game(item, details, status, reason)
        counts[status] = counts.get(status, 0) + 1
        _check_pause()
        if idx % 20 == 0 or idx == total:
            _update(current=idx, cached=cached[0], counts=dict(counts),
                    message=f"写入结果 {idx}/{total}")

    fail_note = f"；{detail_failed} 条详情失败已标记待确认" if detail_failed else ""
    logstore.add("INFO", f"喜加一盘点完成：{counts}")
    _update(state="done", stage="完成", message=f"喜加一盘点完成{fail_note}",
            finished_at=_now(), counts=counts)
