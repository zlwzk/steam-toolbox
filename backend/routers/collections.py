"""库自动分类接口：检测 Steam / 账号、生成预览方案、备份写入、还原备份。

受完整版激活保护：前端未激活时不进入导航，后端在此二次校验，未解锁一律 403。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import collections_engine as engine
from ..collections_data import CATS
from .pro import require_pro

router = APIRouter(prefix="/api/collections", tags=["collections"], dependencies=[Depends(require_pro)])


class PlanPayload(BaseModel):
    accountid: str | None = None
    maxcats: int = 5
    single: bool = False
    overrides: dict | None = None


class WritePayload(BaseModel):
    accountid: str
    games: list[dict]
    dry: bool = False


class AccountPayload(BaseModel):
    accountid: str


def _resolve_account(steam: str, accountid: str | None) -> dict:
    accounts = engine.list_accounts(steam)
    if not accounts:
        raise HTTPException(400, "userdata 下没有账号数据，先登录一次 Steam")
    if accountid:
        match = [a for a in accounts if a["accountid"] == str(accountid)]
        if not match:
            raise HTTPException(400, "没有这个账号：%s" % accountid)
        return match[0]
    return accounts[0]


@router.get("/status")
def status():
    steam = engine.find_steam()
    if not steam:
        return {"steam": None, "accounts": [], "running": engine.steam_running(), "backup": None}
    accounts = engine.list_accounts(steam)
    account = accounts[0] if accounts else None
    backup = engine.last_backup(engine.cloudstorage_dir(account)) if account else None
    return {
        "steam": steam,
        "accounts": [{"accountid": a["accountid"], "name": a["name"]} for a in accounts],
        "running": engine.steam_running(),
        "backup": backup,
    }


@router.post("/plan")
def plan(payload: PlanPayload):
    steam = engine.find_steam()
    if not steam:
        raise HTTPException(400, "没找到 Steam 安装目录，请确认 Steam 已安装并登录过")
    account = _resolve_account(steam, payload.accountid)
    maxcats = 1 if payload.single else max(1, min(5, int(payload.maxcats)))
    try:
        result = engine.build_plan(steam, account, maxcats, payload.overrides)
    except FileNotFoundError as exc:
        raise HTTPException(400, "读取 Steam 缓存失败：%s" % exc) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    result["account"] = {"accountid": account["accountid"], "name": account["name"]}
    return result


@router.post("/write")
def write(payload: WritePayload):
    steam = engine.find_steam()
    if not steam:
        raise HTTPException(400, "没找到 Steam 安装目录")
    account = _resolve_account(steam, payload.accountid)
    if engine.steam_running():
        raise HTTPException(400, "Steam 还在运行，请完全退出（托盘图标右键 → 退出）后再写入")
    # 校验方案：appid 为整数，分类编号必须在 30 个分类内，主分类取第一个
    plan: list[dict] = []
    for g in payload.games:
        try:
            appid = int(g["id"])
            cats = [int(c) for c in g["all"]]
        except (KeyError, TypeError, ValueError):
            raise HTTPException(400, "方案数据格式有误")
        cats = [c for c in cats if c in CATS]
        if not cats:
            continue
        plan.append({"id": appid, "all": cats, "c": cats[0]})
    if not plan:
        raise HTTPException(400, "方案为空，没有可写入的游戏")
    cs = engine.cloudstorage_dir(account)
    try:
        rows, backup = engine.write_collections(cs, plan, dry=payload.dry)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "rows": rows, "backup": backup, "count": len(plan)}


@router.post("/restore")
def restore(payload: AccountPayload):
    steam = engine.find_steam()
    if not steam:
        raise HTTPException(400, "没找到 Steam 安装目录")
    account = _resolve_account(steam, payload.accountid)
    if engine.steam_running():
        raise HTTPException(400, "Steam 还在运行，请完全退出后再还原")
    cs = engine.cloudstorage_dir(account)
    try:
        src = engine.restore_backup(cs)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "backup": src}
