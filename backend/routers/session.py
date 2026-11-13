"""启动会话状态聚合。

软件打开时一次性返回：账号配置是否齐全、浏览器登录态痕迹、版本与内部构建号，
供前端做启动引导。这里只判断本地文件是否存在，不读取、不上传 Cookie / Key 内容。
"""
from __future__ import annotations

from fastapi import APIRouter

from .. import config, database

router = APIRouter(prefix="/api/session", tags=["session"])


def _profile_has_login() -> bool:
    """持久化浏览器 Profile 里是否留有登录 Cookie（仅看 Cookie 痕迹文件是否存在且非空，不读内容）。

    兼容新旧 Chromium 布局：``Default/Cookies``、``Default/Network/Cookies``，
    以及 WAL 未合并时的 ``Cookies-wal``；任一非空即视为留有登录痕迹。
    """
    base = config.DATA_DIR / "browser_profile"
    if not base.exists():
        return False
    for path in base.rglob("Cookies*"):
        try:
            if path.is_file() and path.stat().st_size > 0:
                return True
        except OSError:
            continue
    return False


@router.get("/status")
def session_status() -> dict:
    s = database.get_settings()
    with database.get_conn() as conn:
        owned = conn.execute("SELECT COUNT(*) AS n FROM owned_games").fetchone()["n"]
    has_key = bool(s.get("api_key"))
    has_steamid = bool(s.get("steamid"))
    return {
        "configured": has_key and has_steamid,
        "has_key": has_key,
        "has_steamid": has_steamid,
        "steamid": s.get("steamid", ""),
        "cc": s.get("cc", config.DEFAULT_CC),
        "lang": s.get("lang", config.DEFAULT_LANG),
        "owned_count": owned,
        "profile_exists": _profile_has_login(),
        "version": config.APP_VERSION,
        "build": config.BUILD_NUMBER,
    }
