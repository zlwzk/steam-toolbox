"""库清理接口：规则分析、候选清单、标记、移除登记、导出。"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from .. import cleaner, exporter

router = APIRouter(prefix="/api/cleaner", tags=["cleaner"])


class RulePayload(BaseModel):
    time_mode: str = "never"          # never / lt / gt / range
    threshold: float | None = None
    threshold2: float | None = None
    unit: str = "hour"                # minute / hour
    delisted: str = "exclude"         # keep / exclude / only
    include_paid: bool = False


class MarkPayload(BaseModel):
    field: str
    value: int


class RemovePayload(BaseModel):
    appids: list[int]


@router.post("/analyze")
def analyze(payload: RulePayload):
    return cleaner.analyze(payload.model_dump())


@router.get("/progress")
def progress():
    return cleaner.get_progress()


@router.get("/items")
def items(status: str | None = None):
    return cleaner.list_items(status)


@router.post("/{appid}/mark")
def mark(appid: int, payload: MarkPayload):
    cleaner.mark_item(appid, payload.field, payload.value)
    return {"ok": True}


@router.post("/remove")
def remove(payload: RemovePayload):
    return cleaner.remove_apps(payload.appids)


@router.post("/clear")
def clear():
    cleaner.clear_items()
    return {"ok": True}


@router.get("/export.csv")
def export_csv():
    rows = cleaner.list_items()
    headers = ["AppID", "名称", "时长(分钟)", "原价", "现价", "类型", "是否下架", "状态", "理由"]
    table = [[r["appid"], r["name"], r["playtime_forever"], r["price_initial"],
              r["price_final"], r["app_type"], "是" if r["delisted"] else "否",
              r["status"], r["reason"]] for r in rows]
    return exporter.csv_response("cleaner_items.csv", headers, table)
