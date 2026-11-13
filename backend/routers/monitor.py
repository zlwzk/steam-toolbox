"""更新监控接口：关注游戏 / Mod / 规则 / 事件流 / 订阅动作。"""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel

from .. import database, monitor

router = APIRouter(prefix="/api/monitor", tags=["monitor"])


class GamePayload(BaseModel):
    appid: str
    watch_store: bool = True
    watch_workshop: bool = True


class ModPayload(BaseModel):
    file_id: str
    appid: str = "0"


class RulePayload(BaseModel):
    appid: str = "0"
    keywords: str
    match_mode: str = "any"
    auto_subscribe: bool = False
    enabled: bool = True
    note: str = ""


class SubscribePayload(BaseModel):
    items: list[dict]


class SettingsPayload(BaseModel):
    watch_auto: bool | None = None
    watch_interval_minutes: int | None = None
    watch_auto_subscribe: bool | None = None
    watch_workshop_top: int | None = None


@router.get("/overview")
def overview():
    ov = database.scan_overview()
    games = database.list_watch_games()
    mods = database.list_watch_mods()
    events = database.list_watch_events(limit=50)
    return {
        "watch_games": len(games),
        "watch_mods": len(mods),
        "watch_rules": len(database.list_watch_rules()),
        "watch_unread": ov.get("watch_unread", 0),
        "recent_events": events,
    }


# ---------- 关注游戏 ----------

@router.get("/games")
def games():
    return database.list_watch_games()


@router.post("/games")
def add_game(payload: GamePayload):
    return monitor.add_game(payload.appid, payload.watch_store, payload.watch_workshop)


@router.delete("/games/{appid}")
def delete_game(appid: int):
    database.delete_watch_game(appid)
    return {"ok": True}


# ---------- 关注 Mod ----------

@router.get("/mods")
def mods():
    return database.list_watch_mods()


@router.post("/mods")
def add_mod(payload: ModPayload):
    return monitor.add_mod(payload.file_id, payload.appid)


@router.delete("/mods/{file_id}")
def delete_mod(file_id: int):
    database.delete_watch_mod(file_id)
    return {"ok": True}


# ---------- 关键字规则 ----------

@router.get("/rules")
def rules():
    return database.list_watch_rules()


@router.post("/rules")
def add_rule(payload: RulePayload):
    return monitor.add_rule(payload.appid, payload.keywords, payload.match_mode,
                             payload.auto_subscribe, payload.enabled, payload.note)


@router.put("/rules/{rule_id}")
def update_rule(rule_id: int, payload: RulePayload):
    aid = monitor._valid_appid(payload.appid) if str(payload.appid).strip() not in ("", "0") else 0
    if payload.match_mode not in ("any", "all"):
        raise HTTPException(status_code=400, detail="匹配模式仅支持 any / all")
    kw = monitor._normalize_keywords(payload.keywords)
    ok = database.update_watch_rule(rule_id, aid, kw, payload.match_mode,
                                   1 if payload.auto_subscribe else 0,
                                   1 if payload.enabled else 0, payload.note.strip()[:200])
    return {"ok": ok}


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int):
    database.delete_watch_rule(rule_id)
    return {"ok": True}


# ---------- 事件流 ----------

@router.get("/events")
def events(kind: str | None = None, unread: bool = False, limit: int = 200):
    return database.list_watch_events(kind=kind, only_unread=unread, limit=limit)


@router.post("/events/read")
def read_events(payload: dict = Body(default={})):
    ids = payload.get("ids") if isinstance(payload, dict) else None
    n = database.mark_events_read(ids)
    return {"ok": True, "marked": n}


# ---------- 检测与订阅 ----------

@router.post("/check")
def check():
    return monitor.run_check()


@router.get("/progress")
def progress():
    return monitor.get_progress()


@router.post("/subscribe")
def subscribe(payload: SubscribePayload):
    return monitor.subscribe_items(payload.items)


# ---------- 监控设置 ----------

@router.get("/settings")
def get_settings():
    s = database.get_settings()
    return {
        "watch_auto": s.get("watch_auto", "false").lower() == "true",
        "watch_interval_minutes": int(s.get("watch_interval_minutes", "360")),
        "watch_auto_subscribe": s.get("watch_auto_subscribe", "false").lower() == "true",
        "watch_workshop_top": int(s.get("watch_workshop_top", "20")),
    }


@router.put("/settings")
def save_settings(payload: SettingsPayload):
    updates: dict[str, str] = {}
    if payload.watch_auto is not None:
        updates["watch_auto"] = "true" if payload.watch_auto else "false"
    if payload.watch_interval_minutes is not None:
        if not 15 <= payload.watch_interval_minutes <= 10080:
            raise HTTPException(status_code=400, detail="巡检间隔应在 15–10080 分钟")
        updates["watch_interval_minutes"] = str(payload.watch_interval_minutes)
    if payload.watch_auto_subscribe is not None:
        updates["watch_auto_subscribe"] = "true" if payload.watch_auto_subscribe else "false"
    if payload.watch_workshop_top is not None:
        if not 1 <= payload.watch_workshop_top <= 50:
            raise HTTPException(status_code=400, detail="工坊取样数量应在 1–50")
        updates["watch_workshop_top"] = str(payload.watch_workshop_top)
    if updates:
        database.update_settings(updates)
    return {"ok": True}
