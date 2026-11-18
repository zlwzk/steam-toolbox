"""游戏入库登记接口：名称 / AppID 批量解析、中英文补全和清单登记。

解析仅确认 AppID 和官方名称，不判断价格或拥有状态；登记写入独立的
``wishlist_games`` 表，绝不写入代表真实归属的 ``owned_games``。
本模块不提供领取接口：名称匹配不能证明免费，避免把付费内容交给领取流程。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from .. import app_catalog, database, logstore
from ..app_catalog import MAX_BATCH, STEAM_ACTIVATE_CLIENT, STEAM_ACTIVATE_WEB

router = APIRouter(prefix="/api/wishlist", tags=["wishlist"])


class ResolvePayload(BaseModel):
    inputs: list[str] = Field(default_factory=list)

    @field_validator("inputs")
    @classmethod
    def _check_size(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("请先填写游戏名称或 AppID（每行一条）")
        if len(v) > MAX_BATCH:
            raise ValueError(f"单次最多解析 {MAX_BATCH} 条")
        return v


def _resolver() -> app_catalog.CatalogResolver:
    """使用已保存设置的区域与语言构造解析器（读取设置，不写设置）。"""
    s = database.get_settings()
    return app_catalog.CatalogResolver(cc=s.get("cc"), lang=s.get("lang"))


@router.post("/resolve")
def resolve(payload: ResolvePayload):
    """批量解析名称 / AppID 并补全中英文名称。

    结果逐条返回；解析失败 / 名称缺失的条目按原样标 unresolved / None，
    不猜测、不入库。本接口只做解析预览，不写库。
    """
    resolver = _resolver()
    try:
        results = resolver.resolve_batch(payload.inputs)
    except Exception as exc:  # noqa: BLE001 - 解析异常统一转为可读错误
        raise HTTPException(status_code=502, detail=f"解析失败：{exc}") from exc
    index_info = resolver.load_index()
    return {
        "results": results,
        "index_stale": bool(index_info.get("stale")),
        "index_fetched_at": index_info.get("fetched_at"),
    }


@router.post("/save")
def save(payload: ResolvePayload):
    """解析并登记入库清单（幂等：同输入文本重复登记只更新）。

    unresolved / invalid 条目同样登记（保留输入与原因），用户可在列表中
    看到哪些条目未能确认；名称缺失的字段保持 NULL（未知）。
    """
    resolver = _resolver()
    try:
        results = resolver.resolve_batch(payload.inputs)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"解析失败：{exc}") from exc
    for r in results:
        if r["resolve_status"] == "invalid" and not r["input"]:
            continue  # 超限提示条目不落库
        database.upsert_wishlist_game(
            r["appid"], r["input"], r["resolve_status"], r["source"] or "",
            r["name_en"], r["name_zh"], r["reason"], r["checked_at"],
        )
    saved = len([r for r in results if r["resolve_status"] != "invalid" or r["input"]])
    exact = len([r for r in results if r["resolve_status"] == "exact"])
    unresolved = len([r for r in results if r["resolve_status"] == "unresolved"])
    logstore.add("INFO", f"入库登记：{saved} 条（确认 {exact}，未确认 {unresolved}）")
    return {"ok": True, "saved": saved, "exact": exact, "unresolved": unresolved}


@router.get("/list")
def list_items():
    return database.list_wishlist_games()


@router.delete("/item")
def remove_item(input_text: str = Query(...)):
    removed = database.delete_wishlist_game(input_text)
    if not removed:
        raise HTTPException(status_code=404, detail="条目不存在")
    return {"ok": True}


@router.post("/clear")
def clear_items():
    database.clear_wishlist_games()
    return {"ok": True}


@router.get("/activate-info")
def activate_info():
    """官方激活入口信息（本工具不自动提交激活，见 cdk 模块说明）。"""
    return {
        "web_url": STEAM_ACTIVATE_WEB,
        "client_url": STEAM_ACTIVATE_CLIENT,
        "note": "Steam 未提供公开激活 API；请使用官方入口手动激活，工具不代提交。",
    }
