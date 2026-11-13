"""完整版（Pro）激活态：本机持久化，不联网、不绑机器码、不跨用户/打包产物串通。

激活标记只写入本机 settings 表（pro_unlocked），随本机数据库留存；
删除软件 / 清空 data 目录才会重置。设置页不回显该键，前端隐藏导航的同时，
后端在受保护路由二次校验，双保险。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .. import database

PRO_KEY = "pro_unlocked"

router = APIRouter(prefix="/api/pro", tags=["pro"])


def is_unlocked() -> bool:
    return database.get_setting(PRO_KEY, "false").lower() == "true"


def require_pro() -> bool:
    """路由依赖：未激活完整版时拒绝访问隐藏功能。"""
    if not is_unlocked():
        raise HTTPException(403, "完整版功能尚未激活")
    return True


@router.get("/status")
def status():
    return {"unlocked": is_unlocked()}


@router.post("/unlock")
def unlock():
    database.set_setting(PRO_KEY, "true")
    return {"unlocked": True}
