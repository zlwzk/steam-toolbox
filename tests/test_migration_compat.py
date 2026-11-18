"""旧数据库迁移：旧 schema 重复运行迁移不丢数据；新库幂等初始化。"""
import sqlite3

import pytest

from backend import config, database


def _make_old_db(path):
    """构造 1.2.x 时代的旧库：缺 cover_url / header_image / item_type / ignored 等后加列。"""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE owned_games (appid INTEGER PRIMARY KEY, name TEXT, playtime_forever INTEGER, last_synced_at TEXT);
        CREATE TABLE candidates (dlc_appid INTEGER PRIMARY KEY, status TEXT, reason TEXT, added_at TEXT, updated_at TEXT);
        CREATE TABLE free_games (appid INTEGER PRIMARY KEY, name TEXT, status TEXT, reason TEXT, fetched_at TEXT, added_at TEXT);
        CREATE TABLE claim_records (id INTEGER PRIMARY KEY AUTOINCREMENT, dlc_appid INTEGER, batch_no INTEGER,
                                    status TEXT, reason TEXT, retries INTEGER, claimed_at TEXT, screenshot TEXT);
        CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE dlc_items (dlc_appid INTEGER PRIMARY KEY, parent_appid INTEGER, name TEXT, fetched_at TEXT);
        INSERT INTO owned_games VALUES (730, 'CS2', 120, '2024-01-01T00:00:00');
        INSERT INTO candidates VALUES (80, 'claimable', '免费 DLC', '2024-01-01', '2024-01-01');
        INSERT INTO candidates VALUES (81, 'owned', '已拥有', '2024-01-01', '2024-01-01');
        INSERT INTO free_games VALUES (620, 'Portal', 'limited_free', '喜加一', '2024-01-01', '2024-01-01');
        INSERT INTO claim_records VALUES (1, 80, 0, 'success', 'ok', 0, '2024-01-01', NULL);
        INSERT INTO settings VALUES ('api_key', 'legacy-key');
        INSERT INTO dlc_items VALUES (80, 730, 'Map Pack', '2024-01-01');
    """)
    conn.commit()
    conn.close()


def test_migration_from_old_schema_preserves_rows(tmp_path, monkeypatch):
    db_path = tmp_path / "legacy.db"
    _make_old_db(db_path)
    monkeypatch.setattr(config, "DB_PATH", db_path)

    # 迁移可重复运行：两次 init_db 均成功
    database.init_db()
    database.init_db()

    with database.get_conn() as conn:
        # 旧数据完整保留
        assert conn.execute("SELECT COUNT(*) FROM owned_games").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM free_games").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM claim_records").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM dlc_items").fetchone()[0] == 1
        # 后加列存在且有默认值
        row = conn.execute("SELECT favorite, ignored, item_type, cover_url FROM candidates WHERE dlc_appid = 80").fetchone()
        assert row["favorite"] == 0 and row["ignored"] == 0
        assert row["item_type"] == "dlc"
        # 旧设置保留
        assert conn.execute("SELECT value FROM settings WHERE key = 'api_key'").fetchone()[0] == "legacy-key"


def test_new_db_init_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "fresh.db")
    database.init_db()
    database.init_db()  # 重复初始化不抛错
    with database.get_conn() as conn:
        names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in ("owned_games", "dlc_items", "candidates", "free_games", "claim_records",
                      "claim_queue", "settings", "scan_cache", "workshop_items", "cleaner_items",
                      "watch_games", "watch_mods", "watch_rules", "watch_events"):
            assert table in names
