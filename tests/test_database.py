"""SQLite regression coverage. No network access or Steam credentials needed."""

from backend import config, database


def test_settings_migrate_to_verified_tls_once(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    database.init_db()
    with database.get_conn() as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        conn.execute("DELETE FROM settings WHERE key = 'tls_secure_upgrade_v126'")
        conn.execute("UPDATE settings SET value = 'false' WHERE key = 'verify_ssl'")
    database.init_db()
    assert database.get_setting("verify_ssl") == "true"
    # The operator may opt out explicitly after the migration; respect that choice.
    database.set_setting("verify_ssl", "false")
    database.init_db()
    assert database.get_setting("verify_ssl") == "false"


def test_batch_settings_are_committed_together(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    database.init_db()
    database.update_settings({"fetch_concurrency": "3", "fetch_delay_max": "2.0"})
    assert database.get_setting("fetch_concurrency") == "3"
    assert database.get_setting("fetch_delay_max") == "2.0"
