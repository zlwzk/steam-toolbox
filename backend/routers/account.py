"""账号绑定与连接测试。"""
from __future__ import annotations

import re

from fastapi import APIRouter
from pydantic import BaseModel

from .. import database
from ..steam_client import SteamApiError, SteamClient

router = APIRouter(prefix="/api/account", tags=["account"])

_STEAMID_RE = re.compile(r"^\d{16,18}$")


class AccountPayload(BaseModel):
    api_key: str = ""
    steamid: str = ""
    cc: str = "cn"
    lang: str = "schinese"


@router.get("")
def get_account():
    s = database.get_settings()
    with database.get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM owned_games").fetchone()
    return {
        "has_key": bool(s.get("api_key")),
        "has_steamid": bool(s.get("steamid")),
        "steamid": s.get("steamid", ""),
        "cc": s.get("cc", "cn"),
        "lang": s.get("lang", "schinese"),
        "owned_count": row["n"],
    }


@router.post("")
def save_account(payload: AccountPayload):
    steamid = payload.steamid.strip()
    api_key = payload.api_key.strip()
    if steamid and not _STEAMID_RE.fullmatch(steamid):
        return {"ok": False, "error": "SteamID 应为 17 位纯数字（通常 7656119 开头），请检查是否多填了空格或字母"}
    updates = {
        "steamid": steamid,
        "cc": payload.cc.strip() or "cn",
        "lang": payload.lang.strip() or "schinese",
    }
    if api_key:  # 留空则保留已保存的 Key
        updates["api_key"] = api_key
    try:
        database.update_settings(updates)
    except Exception as exc:  # noqa: BLE001 - 写库失败转友好提示，避免裸 500
        return {"ok": False, "error": f"写入本机数据库失败：{exc}"}
    return {"ok": True}


@router.post("/test")
def test_account(payload: AccountPayload):
    s = database.get_settings()
    api_key = payload.api_key.strip() or s.get("api_key", "")
    steamid = payload.steamid.strip() or s.get("steamid", "")
    cc = payload.cc.strip() or s.get("cc", "cn")
    lang = payload.lang.strip() or s.get("lang", "schinese")
    verify_ssl = s.get("verify_ssl", "true").lower() != "false"
    client = SteamClient(api_key, steamid, cc, lang, verify_ssl)
    try:
        games = client.get_owned_games()
        return {"ok": True, "owned_count": len(games)}
    except SteamApiError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"连接失败：{exc}"}
