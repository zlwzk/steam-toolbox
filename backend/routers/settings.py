"""设置读写（速率参数等）。"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from .. import database, scheduler
from ..settings_validation import EDITABLE_KEYS, validate_settings

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsPayload(BaseModel):
    data: dict


@router.get("")
def get_settings():
    s = database.get_settings()
    # Only expose settings controlled by this page; hide private/internal keys.
    return {k: v for k, v in s.items() if k in EDITABLE_KEYS}


@router.put("")
def update_settings(payload: SettingsPayload):
    existing = database.get_settings()
    updates = validate_settings(payload.data, existing)
    database.update_settings(updates)
    s = database.get_settings()
    return {"ok": True, "settings": {k: v for k, v in s.items() if k in EDITABLE_KEYS}}


@router.get("/scheduler-status")
def scheduler_status():
    return scheduler.get_status()
