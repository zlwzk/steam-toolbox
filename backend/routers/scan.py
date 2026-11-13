"""扫描触发与进度查询。"""
from __future__ import annotations

from fastapi import APIRouter, Query

from .. import scanner

router = APIRouter(prefix="/api/scan", tags=["scan"])


@router.post("/start")
def start_scan(
    kind: str = Query(default="dlc", pattern="^(dlc|freegame)$"),
    force: bool = Query(default=False),
):
    started = scanner.run_scan(kind, force=force)
    return {"ok": started, "kind": kind, "force": force,
            "error": None if started else "已有扫描正在进行或暂停中"}


@router.post("/pause")
def pause_scan():
    ok = scanner.pause_scan()
    return {"ok": ok}


@router.post("/resume")
def resume_scan():
    ok = scanner.resume_scan()
    return {"ok": ok}


@router.get("/progress")
def scan_progress():
    return scanner.get_progress()


@router.get("/overview")
def scan_overview():
    return scanner.get_overview()
