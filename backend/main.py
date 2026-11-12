"""FastAPI 入口。

开发：uvicorn backend.main:app --reload --port 8000
前端单独用 Vite 跑 5173，通过代理 /api 到 8000。
生产：前端 build 到 frontend/dist 后由本服务直接托管。
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import config, database, logstore, scheduler, updater
from .routers import account, candidates, claim, cleaner, freegames, scan, session, settings, workshop

app = FastAPI(title=config.APP_NAME, version=config.APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _no_cache_html(request, call_next):
    """index.html 不缓存，避免升级后浏览器仍加载旧版前端 JS；带 hash 的 assets 由浏览器正常缓存。"""
    resp = await call_next(request)
    if "text/html" in resp.headers.get("content-type", ""):
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


def _setup_logging() -> None:
    """把应用与 uvicorn 日志接入软件内缓冲（无控制台窗口时仍可查看）。"""
    handler = logstore.BufferHandler()
    handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    # uvicorn / error 接入缓冲；access 日志由前端轮询产生，丢弃避免刷满缓冲
    for name in ("uvicorn", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers = [handler]
        lg.propagate = False
    logging.getLogger("uvicorn.access").handlers = []
    logging.getLogger("uvicorn.access").propagate = False


@app.on_event("startup")
def _startup() -> None:
    _setup_logging()
    database.init_db()
    scheduler.start()
    logstore.add("INFO", f"{config.APP_NAME} v{config.APP_VERSION} 已启动")


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/version")
def version():
    return {"name": config.APP_NAME, "version": config.APP_VERSION, "build": config.BUILD_NUMBER}


@app.get("/api/update/check")
def update_check():
    return updater.check()


@app.get("/api/logs")
def get_logs(n: int = 300):
    return {"logs": logstore.get_recent(n)}


@app.post("/api/logs/clear")
def clear_logs():
    logstore.clear()
    return {"ok": True}


app.include_router(account.router)
app.include_router(session.router)
app.include_router(scan.router)
app.include_router(candidates.router)
app.include_router(freegames.router)
app.include_router(claim.router)
app.include_router(workshop.router)
app.include_router(cleaner.router)
app.include_router(settings.router)

_dist = config.RESOURCE_DIR / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=str(_dist), html=True))
