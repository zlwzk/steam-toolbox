"""账号绑定与连接测试。"""
from __future__ import annotations

import re

from fastapi import APIRouter
from pydantic import BaseModel

from .. import config, database
from ..steam_client import SteamApiError, SteamClient

router = APIRouter(prefix="/api/account", tags=["account"])

_STEAMID_RE = re.compile(r"^\d{16,18}$")


class AccountPayload(BaseModel):
    api_key: str = ""
    steamid: str = ""
    cc: str = ""          # 已废弃：商店区由后端自动识别，前端不再提交，后端忽略该字段
    lang: str = ""


def _normalize_lang(raw: str, saved: str) -> str:
    """语言下拉值白名单校验；非法值回退已存值，再回退默认简体中文。"""
    if raw in config.LANG_OPTIONS:
        return raw
    if saved in config.LANG_OPTIONS:
        return saved
    return config.DEFAULT_LANG


def _detect_cc(api_key: str, steamid: str, verify_ssl: bool) -> tuple[str | None, str | None]:
    """识别账号所在商店区。返回 (cc, error)；识别不到时 cc 为 None，error 为可提示原因。"""
    if not api_key or not steamid:
        return None, "缺少 API Key 或 SteamID，暂无法识别区域"
    client = SteamClient(api_key, steamid, config.DEFAULT_CC, config.DEFAULT_LANG, verify_ssl)
    try:
        cc = client.get_country_code()
        if cc:
            return cc, None
        return None, "账号资料未填写所在地或未公开，暂沿用默认商店区"
    except SteamApiError as exc:
        return None, str(exc)
    except Exception as exc:  # noqa: BLE001
        return None, f"区域识别失败：{exc}"


@router.get("")
def get_account():
    s = database.get_settings()
    with database.get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM owned_games").fetchone()
    return {
        "has_key": bool(s.get("api_key")),
        "has_steamid": bool(s.get("steamid")),
        "steamid": s.get("steamid", ""),
        "cc": s.get("cc", config.DEFAULT_CC),
        "lang": s.get("lang", config.DEFAULT_LANG),
        "owned_count": row["n"],
    }


@router.post("")
def save_account(payload: AccountPayload):
    steamid = payload.steamid.strip()
    api_key = payload.api_key.strip()
    if steamid and not _STEAMID_RE.fullmatch(steamid):
        return {"ok": False, "error": "SteamID 应为 17 位纯数字（通常 7656119 开头），请检查是否多填了空格或字母"}

    s = database.get_settings()
    verify_ssl = s.get("verify_ssl", "true").lower() != "false"
    lang = _normalize_lang(payload.lang.strip(), s.get("lang", ""))

    # 商店区自动识别：优先用本次输入的 Key，否则用已存 Key；识别成功覆盖，失败保留已存/默认
    effective_key = api_key or s.get("api_key", "")
    effective_steamid = steamid or s.get("steamid", "")
    detected_cc, detect_err = _detect_cc(effective_key, effective_steamid, verify_ssl)
    cc = detected_cc or s.get("cc") or config.DEFAULT_CC

    updates = {"steamid": effective_steamid, "cc": cc, "lang": lang}
    if api_key:  # 留空则保留已保存的 Key
        updates["api_key"] = api_key
    try:
        database.update_settings(updates)
    except Exception as exc:  # noqa: BLE001 - 写库失败转友好提示，避免裸 500
        return {"ok": False, "error": f"写入本机数据库失败：{exc}"}
    return {"ok": True, "cc": cc, "lang": lang, "cc_detected": bool(detected_cc),
            "cc_note": None if detected_cc else detect_err}


@router.post("/test")
def test_account(payload: AccountPayload):
    s = database.get_settings()
    api_key = payload.api_key.strip() or s.get("api_key", "")
    steamid = payload.steamid.strip() or s.get("steamid", "")
    lang = _normalize_lang(payload.lang.strip(), s.get("lang", ""))
    verify_ssl = s.get("verify_ssl", "true").lower() != "false"

    # 测试时先刷新一次账号区域，再拉取游戏库
    detected_cc, _ = _detect_cc(api_key, steamid, verify_ssl)
    cc = detected_cc or s.get("cc") or config.DEFAULT_CC
    if detected_cc:
        database.set_setting("cc", detected_cc)
    database.set_setting("lang", lang)

    client = SteamClient(api_key, steamid, cc, lang, verify_ssl)
    try:
        games = client.get_owned_games()
        return {"ok": True, "owned_count": len(games), "cc": cc, "lang": lang}
    except SteamApiError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"连接失败：{exc}"}
