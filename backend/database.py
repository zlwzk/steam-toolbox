"""SQLite 存储层（标准库 sqlite3，无 ORM）。"""
from __future__ import annotations

import datetime as dt
import sqlite3
from contextlib import contextmanager
from typing import Iterator

from . import config


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(config.DB_PATH, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL is enabled once by init_db; avoid repeating PRAGMA on every read connection.
    conn.execute("PRAGMA busy_timeout = 5000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS owned_games (
    appid INTEGER PRIMARY KEY,
    name TEXT,
    playtime_forever INTEGER DEFAULT 0,
    last_synced_at TEXT
);

CREATE TABLE IF NOT EXISTS dlc_items (
    dlc_appid INTEGER PRIMARY KEY,
    parent_appid INTEGER,
    name TEXT,
    type TEXT,
    price_initial INTEGER,
    price_final INTEGER,
    currency TEXT,
    cc TEXT,
    supported_languages TEXT,
    review_score TEXT,
    cover_url TEXT,
    header_image TEXT,
    owned INTEGER DEFAULT 0,
    raw_json TEXT,
    fetched_at TEXT
);

CREATE TABLE IF NOT EXISTS candidates (
    dlc_appid INTEGER PRIMARY KEY,
    item_type TEXT DEFAULT 'dlc',
    status TEXT,
    reason TEXT,
    cover_url TEXT,
    added_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS free_games (
    appid INTEGER PRIMARY KEY,
    name TEXT,
    cover_url TEXT,
    header_image TEXT,
    type TEXT,
    price_initial INTEGER,
    price_final INTEGER,
    currency TEXT,
    discount_percent INTEGER,
    supported_languages TEXT,
    review_score TEXT,
    description TEXT,
    status TEXT,
    reason TEXT,
    fetched_at TEXT,
    added_at TEXT
);

CREATE TABLE IF NOT EXISTS claim_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dlc_appid INTEGER,
    batch_no INTEGER,
    status TEXT,
    reason TEXT,
    retries INTEGER DEFAULT 0,
    claimed_at TEXT,
    screenshot TEXT
);

CREATE TABLE IF NOT EXISTS claim_queue (
    appid INTEGER,
    item_kind TEXT DEFAULT 'dlc',
    name TEXT,
    status TEXT DEFAULT 'pending',
    updated_at TEXT,
    PRIMARY KEY (appid, item_kind)
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS scan_cache (
    appid INTEGER PRIMARY KEY,
    body TEXT,
    fetched_at TEXT
);

CREATE TABLE IF NOT EXISTS workshop_items (
    published_file_id INTEGER PRIMARY KEY,
    appid INTEGER,
    title TEXT,
    status TEXT,
    reason TEXT,
    cover_url TEXT,
    favorite INTEGER DEFAULT 0,
    ignored INTEGER DEFAULT 0,
    added_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS cleaner_items (
    appid INTEGER PRIMARY KEY,
    name TEXT,
    playtime_forever INTEGER DEFAULT 0,
    price_initial INTEGER,
    price_final INTEGER,
    app_type TEXT,
    delisted INTEGER DEFAULT 0,
    status TEXT,
    reason TEXT,
    cover_url TEXT,
    favorite INTEGER DEFAULT 0,
    ignored INTEGER DEFAULT 0,
    fetched_at TEXT
);

CREATE TABLE IF NOT EXISTS watch_games (
    appid INTEGER PRIMARY KEY,
    name TEXT,
    cover_url TEXT,
    watch_store INTEGER DEFAULT 1,
    watch_workshop INTEGER DEFAULT 1,
    last_fingerprint TEXT,
    last_workshop_top TEXT,
    last_checked_at TEXT,
    last_change TEXT,
    added_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS watch_mods (
    published_file_id INTEGER PRIMARY KEY,
    appid INTEGER,
    title TEXT,
    cover_url TEXT,
    file_size INTEGER DEFAULT 0,
    time_updated INTEGER DEFAULT 0,
    last_time_updated INTEGER DEFAULT 0,
    last_file_size INTEGER DEFAULT 0,
    subscribed INTEGER DEFAULT 0,
    last_checked_at TEXT,
    change_note TEXT,
    added_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS watch_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    appid INTEGER DEFAULT 0,
    keywords TEXT,
    match_mode TEXT DEFAULT 'any',
    auto_subscribe INTEGER DEFAULT 0,
    enabled INTEGER DEFAULT 1,
    note TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS watch_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT,
    appid INTEGER,
    file_id INTEGER,
    title TEXT,
    detail TEXT,
    detected_at TEXT,
    seen INTEGER DEFAULT 0,
    action TEXT DEFAULT 'none'
);
"""

# 旧库兜底迁移：补充后加的列
MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "dlc_items": [
        ("cover_url", "TEXT"),
        ("header_image", "TEXT"),
    ],
    "candidates": [
        ("item_type", "TEXT DEFAULT 'dlc'"),
        ("cover_url", "TEXT"),
        ("ignored", "INTEGER DEFAULT 0"),
        ("favorite", "INTEGER DEFAULT 0"),
    ],
    "free_games": [
        ("ignored", "INTEGER DEFAULT 0"),
        ("favorite", "INTEGER DEFAULT 0"),
    ],
    "claim_records": [
        ("item_kind", "TEXT DEFAULT 'dlc'"),
    ],
}


def _migrate(conn: sqlite3.Connection) -> None:
    for table, columns in MIGRATIONS.items():
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for col, decl in columns:
            if col not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


def init_db() -> None:
    with get_conn() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        _migrate(conn)
        for key, value in config.DEFAULT_SETTINGS.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
                (key, value),
            )
        _tune_fetch_defaults(conn)
        _enable_tls_by_default_once(conn)


def _enable_tls_by_default_once(conn: sqlite3.Connection) -> None:
    """One-time security migration. Explicit opt-out *after* upgrade is preserved."""
    marker = "tls_secure_upgrade_v126"
    seen = conn.execute("SELECT 1 FROM settings WHERE key = ?", (marker,)).fetchone()
    if seen is None:
        conn.execute("UPDATE settings SET value = 'true' WHERE key = 'verify_ssl' AND value = 'false'")
        conn.execute("INSERT INTO settings(key, value) VALUES (?, 'true')", (marker,))


def _tune_fetch_defaults(conn: sqlite3.Connection) -> None:
    """一次性提速迁移：早期版本把抓取间隔固化为 1.5–4.0s、并发 2（偏慢）。

    仅当现存值仍是这组早期保守默认时，刷新为当前默认节奏；用户在设置页
    手动改过的间隔/并发保持不动。条件幂等，重复启动不会反复覆盖。
    """
    def val(key: str) -> str | None:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    if val("fetch_delay_min") == "1.5" and val("fetch_delay_max") == "4.0":
        conn.execute("UPDATE settings SET value = ? WHERE key = 'fetch_delay_min'",
                     (str(config.FETCH_DELAY_MIN),))
        conn.execute("UPDATE settings SET value = ? WHERE key = 'fetch_delay_max'",
                     (str(config.FETCH_DELAY_MAX),))
        if val("fetch_concurrency") == "2":
            conn.execute("UPDATE settings SET value = ? WHERE key = 'fetch_concurrency'",
                         (str(config.FETCH_CONCURRENCY),))


def get_setting(key: str, default: str | None = None) -> str:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is not None:
        return row["value"]
    if default is not None:
        return default
    return config.DEFAULT_SETTINGS.get(key, "")


def get_settings() -> dict[str, str]:
    with get_conn() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    return {r["key"]: r["value"] for r in rows}


def set_setting(key: str, value: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )


def update_settings(data: dict[str, str]) -> None:
    """Commit all settings together so failures cannot leave partial edits."""
    with get_conn() as conn:
        conn.executemany(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            [(key, str(value)) for key, value in data.items()],
        )


# ---------- 领取队列（本机持久化，中断后续跑） ----------

def save_claim_queue(items: list[dict]) -> None:
    """重置领取队列为传入条目（pending）。items: [{appid, kind, name}]。"""
    now = dt.datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        conn.execute("DELETE FROM claim_queue")
        for it in items:
            conn.execute(
                "INSERT INTO claim_queue(appid, item_kind, name, status, updated_at) "
                "VALUES (?, ?, ?, 'pending', ?)",
                (it["appid"], it.get("kind", "dlc"), it.get("name", ""), now),
            )


def pending_claim_queue() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT appid, item_kind, name FROM claim_queue WHERE status = 'pending' ORDER BY updated_at, appid"
        ).fetchall()
    return [{"appid": r["appid"], "kind": r["item_kind"], "name": r["name"]} for r in rows]


def mark_claim_done(appid: int, kind: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE claim_queue SET status = 'done', updated_at = ? WHERE appid = ? AND item_kind = ?",
            (dt.datetime.now().isoformat(timespec="seconds"), appid, kind),
        )


def clear_claim_queue() -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM claim_queue")


def latest_claim_status() -> dict[tuple[int, str], str]:
    """每个条目最新一条领取记录状态，用于续跑时跳过已成功/已在库项。"""
    out: dict[tuple[int, str], str] = {}
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT dlc_appid, item_kind, status FROM claim_records r "
            "WHERE id IN (SELECT MAX(id) FROM claim_records GROUP BY dlc_appid, item_kind)"
        ).fetchall()
    for r in rows:
        out[(r["dlc_appid"], r["item_kind"])] = r["status"]
    return out


def clear_cache() -> int:
    """清空详情缓存，返回删除条数；用于强制全量重扫。"""
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM scan_cache")
        return cur.rowcount


def scan_overview() -> dict:
    """汇总已有盘点结果与最近扫描时间，供扫描页避免重复扫描提示。"""
    with get_conn() as conn:
        owned = conn.execute("SELECT COUNT(*) AS n FROM owned_games").fetchone()["n"]
        dlc_rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM candidates WHERE item_type = 'dlc' GROUP BY status"
        ).fetchall()
        free_rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM free_games GROUP BY status"
        ).fetchall()
        last = conn.execute(
            "SELECT MAX(t) AS last FROM ("
            "  SELECT MAX(updated_at) AS t FROM candidates "
            "  UNION ALL SELECT MAX(fetched_at) AS t FROM free_games"
            ") "
        ).fetchone()["last"]
        ws_rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM workshop_items GROUP BY status"
        ).fetchall()
        cl_rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM cleaner_items GROUP BY status"
        ).fetchall()
        ev_unread = conn.execute(
            "SELECT COUNT(*) AS n FROM watch_events WHERE seen = 0"
        ).fetchone()["n"]

    dlc = {r["status"]: r["n"] for r in dlc_rows}
    free = {r["status"]: r["n"] for r in free_rows}
    ws = {r["status"]: r["n"] for r in ws_rows}
    cl = {r["status"]: r["n"] for r in cl_rows}
    return {
        "owned": owned,
        "dlc_total": sum(dlc.values()),
        "dlc_claimable": dlc.get("claimable", 0),
        "free_total": sum(free.values()),
        "free_limited": free.get("limited_free", 0),
        "ws_total": sum(ws.values()),
        "ws_pending": ws.get("pending", 0),
        "cleaner_total": sum(cl.values()),
        "cleaner_candidate": cl.get("candidate", 0),
        "watch_unread": ev_unread,
        "last_scan_at": last,
    }


# ---------- 更新监控（本机留存，不上传） ----------

def upsert_watch_game(appid: int, name: str = "", cover_url: str = "",
                      watch_store: int = 1, watch_workshop: int = 1) -> None:
    now = dt.datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO watch_games(appid, name, cover_url, watch_store, watch_workshop, added_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(appid) DO UPDATE SET name=excluded.name, cover_url=excluded.cover_url, "
            "watch_store=excluded.watch_store, watch_workshop=excluded.watch_workshop, updated_at=excluded.updated_at",
            (appid, name, cover_url, watch_store, watch_workshop, now, now),
        )


def list_watch_games() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM watch_games ORDER BY updated_at DESC").fetchall()
    return [dict(r) for r in rows]


def get_watch_game(appid: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM watch_games WHERE appid = ?", (appid,)).fetchone()
    return dict(row) if row else None


def update_watch_game_snapshot(appid: int, fingerprint: str | None,
                               workshop_top: str | None, change: str) -> None:
    now = dt.datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        conn.execute(
            "UPDATE watch_games SET last_fingerprint=?, last_workshop_top=?, last_checked_at=?, "
            "last_change=?, updated_at=? WHERE appid=?",
            (fingerprint, workshop_top, now, change, now, appid),
        )


def delete_watch_game(appid: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM watch_games WHERE appid = ?", (appid,))


def upsert_watch_mod(file_id: int, appid: int, title: str = "", cover_url: str = "",
                     file_size: int = 0, time_updated: int = 0, subscribed: int = 0) -> None:
    now = dt.datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO watch_mods(published_file_id, appid, title, cover_url, file_size, time_updated, "
            "last_time_updated, last_file_size, subscribed, added_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(published_file_id) DO UPDATE SET appid=excluded.appid, title=excluded.title, "
            "cover_url=excluded.cover_url, file_size=excluded.file_size, time_updated=excluded.time_updated, "
            "subscribed=excluded.subscribed, updated_at=excluded.updated_at",
            (file_id, appid, title, cover_url, file_size, time_updated, time_updated, file_size,
             subscribed, now, now),
        )


def list_watch_mods() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM watch_mods ORDER BY updated_at DESC").fetchall()
    return [dict(r) for r in rows]


def get_watch_mod(file_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM watch_mods WHERE published_file_id = ?", (file_id,)).fetchone()
    return dict(row) if row else None


def update_watch_mod_snapshot(file_id: int, file_size: int, time_updated: int,
                              change_note: str) -> None:
    now = dt.datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        conn.execute(
            "UPDATE watch_mods SET last_time_updated=time_updated, last_file_size=file_size, "
            "file_size=?, time_updated=?, last_checked_at=?, change_note=?, updated_at=? "
            "WHERE published_file_id=?",
            (file_size, time_updated, now, change_note, now, file_id),
        )


def mark_watch_mod_subscribed(file_id: int, subscribed: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE watch_mods SET subscribed=?, updated_at=? WHERE published_file_id=?",
            (subscribed, dt.datetime.now().isoformat(timespec="seconds"), file_id),
        )


def delete_watch_mod(file_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM watch_mods WHERE published_file_id = ?", (file_id,))


def add_watch_rule(appid: int, keywords: str, match_mode: str, auto_subscribe: int,
                   enabled: int, note: str) -> int:
    now = dt.datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO watch_rules(appid, keywords, match_mode, auto_subscribe, enabled, note, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (appid, keywords, match_mode, auto_subscribe, enabled, note, now),
        )
        return cur.lastrowid


def list_watch_rules() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM watch_rules ORDER BY id ASC").fetchall()
    return [dict(r) for r in rows]


def update_watch_rule(rule_id: int, appid: int, keywords: str, match_mode: str,
                      auto_subscribe: int, enabled: int, note: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE watch_rules SET appid=?, keywords=?, match_mode=?, auto_subscribe=?, enabled=?, note=? "
            "WHERE id=?",
            (appid, keywords, match_mode, auto_subscribe, enabled, note, rule_id),
        )
        return cur.rowcount > 0


def delete_watch_rule(rule_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM watch_rules WHERE id = ?", (rule_id,))


def add_watch_event(kind: str, appid: int | None, file_id: int | None, title: str,
                    detail: str, action: str = "none") -> int:
    now = dt.datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO watch_events(kind, appid, file_id, title, detail, detected_at, seen, action) "
            "VALUES (?, ?, ?, ?, ?, ?, 0, ?)",
            (kind, appid, file_id, title, detail, now, action),
        )
        return cur.lastrowid


def list_watch_events(kind: str | None = None, only_unread: bool = False,
                      limit: int = 200) -> list[dict]:
    sql = "SELECT * FROM watch_events WHERE 1=1"
    args: list = []
    if kind:
        sql += " AND kind = ?"
        args.append(kind)
    if only_unread:
        sql += " AND seen = 0"
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    with get_conn() as conn:
        rows = conn.execute(sql, args).fetchall()
    return [dict(r) for r in rows]


def mark_events_read(event_ids: list[int] | None = None) -> int:
    with get_conn() as conn:
        if event_ids:
            placeholders = ",".join("?" for _ in event_ids)
            cur = conn.execute(
                f"UPDATE watch_events SET seen = 1 WHERE id IN ({placeholders})", event_ids
            )
        else:
            cur = conn.execute("UPDATE watch_events SET seen = 1 WHERE seen = 0")
        return cur.rowcount
