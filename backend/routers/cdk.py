"""CDK 登记与人工激活辅助接口（不自动提交激活，见 backend/cdk.py 说明）。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from .. import app_catalog, cdk

router = APIRouter(prefix="/api/cdk", tags=["cdk"])


class KeysPayload(BaseModel):
    keys: list[str] = Field(default_factory=list)
    note: str = ""

    @field_validator("keys")
    @classmethod
    def _check_size(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("请先填写激活码（每行一条）")
        if len(v) > 200:
            raise ValueError("单次最多登记 200 条")
        return v


class ConfirmPayload(BaseModel):
    ids: list[int] = Field(default_factory=list)

    @field_validator("ids")
    @classmethod
    def _check_ids(cls, v: list[int]) -> list[int]:
        if not v:
            raise ValueError("请先选择要确认的激活码")
        if len(v) > 200:
            raise ValueError("单次最多确认 200 条")
        return v


class StatusPayload(BaseModel):
    id: int
    status: str
    reason: str = Field(default="", max_length=500)


@router.post("/add")
def add(payload: KeysPayload):
    """批量登记激活码（ready / invalid），不产生任何网络请求。"""
    return cdk.add_keys(payload.keys, payload.note)


@router.get("/list")
def list_keys(status: str = Query(default=""), limit: int = Query(default=500, ge=1, le=2000)):
    """列表：key 掩码返回；状态统计随附。"""
    return cdk.list_keys(status, limit)


@router.post("/confirm")
def confirm(payload: ConfirmPayload):
    """逐条二次确认（格式复验 → ready）；不产生网络请求，不提交激活。"""
    return cdk.confirm_keys(payload.ids)


@router.post("/status")
def mark(payload: StatusPayload):
    """用户手动标记激活结果（activated / failed / ready）。

    activated 只能由用户显式标记——工具无法核验 Steam 侧结果。
    """
    r = cdk.mark_status(payload.id, payload.status, payload.reason)
    if not r.get("ok"):
        raise HTTPException(status_code=400, detail=r.get("error", "操作失败"))
    return r


@router.delete("/{key_id}")
def remove(key_id: int):
    r = cdk.remove_key(key_id)
    if not r.get("ok"):
        raise HTTPException(status_code=404, detail=r.get("error", "条目不存在"))
    return {"ok": True}


@router.get("/reveal/{key_id}")
def reveal(key_id: int):
    """显式取回单条明文（复制到 Steam 客户端使用），带审计日志。"""
    r = cdk.reveal_key(key_id)
    if not r.get("ok"):
        raise HTTPException(status_code=404, detail=r.get("error", "条目不存在"))
    return r


@router.get("/activate-info")
def activate_info():
    """官方激活入口（web 页面与 steam:// 协议）；工具不代提交。"""
    return {
        "web_url": app_catalog.STEAM_ACTIVATE_WEB,
        "client_url": app_catalog.STEAM_ACTIVATE_CLIENT,
        "note": "请复制激活码后在 Steam 官方入口完成激活；激活结果请回到本页手动标记。",
    }
