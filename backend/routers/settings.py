"""设置读写（速率参数等）。"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from .. import database, scheduler

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsPayload(BaseModel):
    data: dict


@router.get("")
def get_settings():
    s = database.get_settings()
    # API Key 不下发到前端（账号页仅用 has_key 布尔判断），避免明文出现在页面/内存表单
    s.pop("api_key", None)
    return s


@router.put("")
def update_settings(payload: SettingsPayload):
    database.update_settings(payload.data)
    return {"ok": True, "settings": database.get_settings()}


@router.get("/scheduler-status")
def scheduler_status():
    return scheduler.get_status()
