"""创意工坊批量订阅 / 退订接口。"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from .. import exporter, workshop

router = APIRouter(prefix="/api/workshop", tags=["workshop"])


class StartPayload(BaseModel):
    appid: str
    mode: str = "subscribe"          # subscribe / unsubscribe
    auto: bool = False
    range_start: int = 0
    range_end: int = 0


class MarkPayload(BaseModel):
    field: str
    value: int


@router.post("/start")
def start(payload: StartPayload):
    return workshop.start_task(payload.appid, payload.mode, payload.auto,
                               payload.range_start, payload.range_end)


@router.post("/pause")
def pause():
    return workshop.pause_task()


@router.post("/cancel")
def cancel():
    return workshop.cancel_task()


@router.post("/retry-failed")
def retry_failed():
    return workshop.retry_failed()


@router.get("/progress")
def progress():
    return workshop.get_progress()


@router.get("/items")
def items(status: str | None = None):
    return workshop.list_items(status)


@router.post("/{pid}/mark")
def mark(pid: int, payload: MarkPayload):
    workshop.mark_item(pid, payload.field, payload.value)
    return {"ok": True}


@router.post("/clear")
def clear():
    workshop.clear_items()
    return {"ok": True}


@router.get("/export.csv")
def export_csv():
    rows = workshop.list_items()
    headers = ["文件ID", "AppID", "标题", "状态", "理由", "更新时间"]
    table = [[r["published_file_id"], r["appid"], r["title"], r["status"],
              r["reason"], r["updated_at"]] for r in rows]
    return exporter.csv_response("workshop_items.csv", headers, table)
