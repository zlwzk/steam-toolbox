"""更新检查：对比本机版本与 GitHub 最新 Release，仅做只读查询，不上传任何本机信息。

- 只访问 api.github.com 读取最新 Release 元数据；不下载、不替换程序文件。
- 结果在进程内缓存一段时间，避免每次打开界面都请求网络。
- 网络不可达 / 解析失败时静默返回「无更新」，不影响软件正常使用。
"""
from __future__ import annotations

import re
import threading
import time

import requests

from . import ca_store, config

REPO = "zlwzk/steam-toolbox"
_API = f"https://api.github.com/repos/{REPO}/releases/latest"
_RELEASE_PAGE = f"https://github.com/{REPO}/releases/latest"
_CACHE_TTL = 30 * 60  # 秒
_lock = threading.Lock()
_cache: dict = {"at": 0.0, "data": None}


def _parse_version(v: str) -> tuple[int, ...]:
    """把 'v1.2.0' / '1.2.0-rc.1' 解析为可比较的数字元组，非数字段按 0 处理。"""
    v = (v or "").lstrip("vV").strip()
    nums: list[int] = []
    for part in re.split(r"[.\-+]", v):
        m = re.match(r"\d+", part)
        nums.append(int(m.group()) if m else 0)
    return tuple(nums) if nums else (0,)


def _fetch_latest() -> dict:
    resp = requests.get(
        _API,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "SteamToolbox-Updater"},
        timeout=8,
        verify=ca_store.bundle_path(),
    )
    resp.raise_for_status()
    data = resp.json()
    return {
        "latest": str(data.get("tag_name") or "").lstrip("vV"),
        "release_url": data.get("html_url") or _RELEASE_PAGE,
        "notes": data.get("body") or "",
        "name": data.get("name") or "",
    }


def check(force: bool = False) -> dict:
    """返回 {current, build, latest, available, release_url, notes, name}。"""
    current = config.APP_VERSION
    now = time.time()
    with _lock:
        if not force and _cache["data"] and now - _cache["at"] < _CACHE_TTL:
            base = dict(_cache["data"])
            base["current"] = current
            base["build"] = config.BUILD_NUMBER
            return base

    result: dict = {
        "current": current,
        "build": config.BUILD_NUMBER,
        "latest": None,
        "available": False,
        "release_url": _RELEASE_PAGE,
        "notes": "",
        "name": "",
    }
    try:
        latest = _fetch_latest()
        result.update(latest)
        result["available"] = _parse_version(latest["latest"]) > _parse_version(current)
        with _lock:
            _cache["at"] = now
            _cache["data"] = dict(result)
    except Exception:  # noqa: BLE001 - 网络失败不阻断使用，按无更新处理
        result["available"] = False
    return result
