"""领取任务：开始领取、进度、记录、手动登录。"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from .. import claimer, database, exporter

router = APIRouter(prefix="/api/claim", tags=["claim"])


class ClaimItem(BaseModel):
    appid: int
    kind: str = "dlc"
    name: str = ""


class ClaimPayload(BaseModel):
    items: list[ClaimItem]


@router.post("/start")
def start_claim(payload: ClaimPayload):
    items = [i.model_dump() for i in payload.items]
    if not items:
        return {"ok": False, "error": "未选择可领取条目"}
    claimer.start_claim(items)
    return {"ok": True, "count": len(items)}


@router.post("/resume")
def resume_claim():
    return claimer.resume_claim()


@router.get("/progress")
def claim_progress():
    return claimer.get_progress()


@router.get("/records")
def records(limit: int = 200):
    return claimer.list_records(limit)


@router.get("/export.csv")
def export_records(limit: int = 1000):
    rows = claimer.list_records(limit)
    headers = ["时间", "类型", "AppID", "状态", "理由", "重试次数", "截图"]
    table = [
        [r["claimed_at"], r["item_kind"], r["dlc_appid"], r["status"], r["reason"],
         r["retries"], r["screenshot"]]
        for r in rows
    ]
    return exporter.csv_response("claim_records.csv", headers, table)


@router.post("/login")
def login():
    try:
        claimer.open_login_window()
        return {"ok": True}
    except claimer.ClaimError as exc:
        return {"ok": False, "error": str(exc)}
