"""游戏名称 / AppID 解析器：把用户输入解析为可核验的 AppID 并补全中英文名称。

设计约束（与仓库既有安全原则一致）
----------------------------------
* 只使用 Steam 官方数据源：
  - ISteamApps/GetAppList/v2/  全量 AppID + 名称索引（公开、无需 API Key）
  - store.steampowered.com/search/results  商店名称搜索（支持本地化语言）
  - store.steampowered.com/api/appdetails  按语言读取官方名称
* 不伪造：无法确认 AppID 时保留 ``appid = None`` 与 ``unresolved`` 状态，
  不猜测、不默认成功、不把「未查到」当成免费 / 已拥有 / 已下架。
* 名称补全失败时字段保持 ``None``（未知），不做机翻、不拼接猜测值。
* 中英文补全走独立请求，**不写入 SteamClient 的 scan_cache**：
  该缓存按 appid 单键存储、不区分语言，复用会串味。
* 所有外部请求经 Throttler 全局闸门，保留 TLS 校验与 429/5xx 退避。
* 全部网络入口集中在 ``_get`` / ``_download_app_list``，便于测试完整 mock。
"""
from __future__ import annotations

import datetime as dt
import json
import re
import threading
import unicodedata
from pathlib import Path

from . import config, logstore
from .steam_client import SteamClient
from .throttler import ThrottleConfig, Throttler

APP_LIST_URL = f"{config.STEAM_API_BASE}/ISteamApps/GetAppList/v2/"
STORE_SEARCH_URL = config.STORE_SEARCH_BASE
APPDETAILS_URL = f"{config.STORE_API_BASE}/appdetails"

# 官方激活入口（本模块只登记与生成入口，不自动提交，见 cdk 模块说明）
STEAM_ACTIVATE_WEB = "https://store.steampowered.com/account/registerkey"
STEAM_ACTIVATE_CLIENT = "steam://open/activateproduct"

# 单次批量解析上限：避免一次操作产生过多外部请求，保持保守限速
MAX_BATCH = 50
# 商店搜索单次返回候选数
SEARCH_COUNT = 10

_INDEX_FILE = "app_catalog_index.json"
_index_lock = threading.Lock()
_index_cache: dict | None = None

_PUNCT_RE = re.compile(r"[\s\-_:;,.!?/\\|·•™®©()（）\[\]【】<>《》\"'`]+")


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def normalize(value: str) -> str:
    """名称归一化：全角转半角、去空白与常见标点、转小写。仅用于比较，不改写原始值。"""
    if not value:
        return ""
    s = unicodedata.normalize("NFKC", str(value))
    return _PUNCT_RE.sub("", s).lower()


def _cache_path() -> Path:
    return config.DATA_DIR / _INDEX_FILE


def _ttl_seconds() -> float:
    return float(config.CACHE_TTL_HOURS) * 3600


def _is_fresh(fetched_at: str | None) -> bool:
    if not fetched_at:
        return False
    try:
        return (dt.datetime.now() - dt.datetime.fromisoformat(fetched_at)).total_seconds() < _ttl_seconds()
    except (ValueError, TypeError):
        return False


def _read_index_file() -> dict | None:
    """读取本地索引缓存；文件损坏时返回 None，不抛出。"""
    global _index_cache
    if _index_cache is not None:
        return _index_cache
    path = _cache_path()
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data.get("apps"), list):
            return None
        _index_cache = data
        return data
    except (OSError, ValueError, TypeError):
        return None


def _write_index_file(data: dict) -> None:
    """原子写入索引缓存，避免并发写导致半文件。"""
    global _index_cache
    path = _cache_path()
    tmp = path.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
        _index_cache = data
    except OSError as exc:
        logstore.add("WARN", f"游戏目录索引缓存写入失败（不影响本次解析）：{exc}")


def _default_throttler() -> Throttler:
    return Throttler(ThrottleConfig(
        delay_min=float(config.FETCH_DELAY_MIN),
        delay_max=float(config.FETCH_DELAY_MAX),
    ))


class CatalogResolver:
    """名称 / ID → AppID 解析器。所有网络调用可经 ``_get`` 注入或 monkeypatch。"""

    def __init__(self, client: SteamClient | None = None, throttler: Throttler | None = None,
                 cc: str | None = None, lang: str | None = None):
        self._client = client
        self._thr = throttler
        self.cc = cc or config.DEFAULT_CC
        self.lang = lang or config.DEFAULT_LANG

    @property
    def client(self) -> SteamClient:
        if self._client is None:
            self._client = SteamClient("", "", self.cc, self.lang)
        return self._client

    @property
    def thr(self) -> Throttler:
        if self._thr is None:
            self._thr = _default_throttler()
        return self._thr

    # ---------- 底层请求（唯一网络出口） ----------

    def _get(self, url: str, params: dict):
        """经全局闸门发请求；复用 SteamClient 的 TLS 校验与 429/5xx 退避。"""
        self.thr.gate()
        return self.client._get_json(url, params)

    def _download_app_list(self) -> list[list]:
        data = self._get(APP_LIST_URL, {})
        apps = (data or {}).get("applist", {}).get("apps", [])
        out = []
        for row in apps or []:
            appid = row.get("appid")
            name = row.get("name")
            if isinstance(appid, int) and isinstance(name, str) and name.strip():
                out.append([appid, name])
        return out

    # ---------- 全量索引 ----------

    def load_index(self, force: bool = False) -> dict:
        """返回 ``{"apps": [[appid, name], ...], "fetched_at": str, "stale": bool}``。

        缓存过期 / 强制刷新时重新拉取；拉取失败则退回旧缓存并标 ``stale``，
        没有任何缓存时返回空索引（解析退化为商店搜索，绝不猜测）。
        """
        with _index_lock:
            cached = _read_index_file()
            if not force and cached and _is_fresh(cached.get("fetched_at")):
                return {**cached, "stale": False}
            try:
                apps = self._download_app_list()
                if not apps:
                    raise ValueError("GetAppList 返回空列表")
                fresh = {"apps": apps, "fetched_at": _now()}
                _write_index_file(fresh)
                return {**fresh, "stale": False}
            except Exception as exc:  # noqa: BLE001 - 目录拉取失败不应阻断其它解析路径
                logstore.add("WARN", f"Steam 游戏目录索引刷新失败：{exc}")
                if cached:
                    return {**cached, "stale": True}
                return {"apps": [], "fetched_at": None, "stale": True}

    def refresh_index(self) -> dict:
        info = self.load_index(force=True)
        return {"count": len(info.get("apps") or []), "fetched_at": info.get("fetched_at"),
                "stale": bool(info.get("stale"))}

    @staticmethod
    def _index_matches(index: dict, query: str) -> tuple[list[int], list[dict]]:
        """归一化后精确匹配；无精确命中时给出有限子串候选（仅供用户选择，不自动采用）。"""
        target = normalize(query)
        if not target:
            return [], []
        exact: list[int] = []
        candidates: list[dict] = []
        for appid, name in index.get("apps") or []:
            n = normalize(name)
            if not n:
                continue
            if n == target:
                exact.append(appid)
            elif len(candidates) < 8 and (target in n or n in target):
                candidates.append({"appid": appid, "name": name, "source": "app_list"})
        return exact[:8], candidates

    # ---------- 商店搜索 ----------

    def _search_store(self, query: str, lang: str) -> list[dict]:
        try:
            data = self._get(STORE_SEARCH_URL, {
                "query": query, "start": 0, "count": SEARCH_COUNT,
                "cc": self.cc, "l": lang, "json": 1,
            })
        except Exception as exc:  # noqa: BLE001 - 单个语言搜索失败不影响另一语言
            logstore.add("WARN", f"商店搜索失败（{lang}）：{exc}")
            return []
        items = []
        for it in (data or {}).get("items", []) or []:
            logo = it.get("logo", "") or ""
            m = re.search(r"/apps/(\d+)/", logo)
            if not m:
                continue
            items.append({"appid": int(m.group(1)), "name": it.get("name", "") or "",
                          "source": "store_search"})
        return items

    # ---------- 中英文名称补全 ----------

    def _name_for_lang(self, appid: int, lang: str) -> str | None:
        """按指定语言读取官方名称；失败/无数据返回 None（未知），不写共享缓存。"""
        try:
            data = self._get(APPDETAILS_URL, {
                "appids": str(appid), "cc": self.cc, "l": lang, "filters": "basic",
            })
        except Exception as exc:  # noqa: BLE001 - 详情缺失一律保留未知
            logstore.add("WARN", f"AppID {appid} 名称补全失败（{lang}）：{exc}")
            return None
        node = (data or {}).get(str(appid)) or {}
        if not node.get("success"):
            return None
        name = (node.get("data") or {}).get("name")
        return name if isinstance(name, str) and name.strip() else None

    def fetch_names(self, appid: int) -> dict:
        """返回中英文官方名称与检查时间；任一语言失败则该字段为 None。"""
        return {
            "name_en": self._name_for_lang(appid, "english"),
            "name_zh": self._name_for_lang(appid, "schinese"),
            "checked_at": _now(),
        }

    # ---------- 对外解析 ----------

    def resolve_one(self, text: str) -> dict:
        raw = str(text or "").strip()
        base = {
            "input": raw, "appid": None, "name_en": None, "name_zh": None,
            "resolve_status": "unresolved", "source": None, "raw_name": None,
            "checked_at": None, "candidates": [], "reason": "",
        }
        if not raw:
            return {**base, "resolve_status": "invalid", "reason": "输入为空"}
        if len(raw) > 200:
            return {**base, "resolve_status": "invalid", "reason": "单条输入过长（上限 200 字符）"}

        # 1) 纯数字视为 AppID；AppID 本身确定，名称仍需向官方核验
        if raw.isdigit() and 1 <= int(raw) <= 2_147_483_647:
            appid = int(raw)
            names = self.fetch_names(appid)
            status = "exact" if (names["name_en"] or names["name_zh"]) else "appid_only"
            return {**base, "appid": appid, **names, "resolve_status": status,
                    "source": "direct_appid",
                    "reason": "AppID 已确认" if status == "exact" else "AppID 已确认，但官方名称获取失败，名称保留为未知"}

        # 2) 全量索引精确匹配（大小写 / 空格 / 全半角归一化）
        index = self.load_index()
        exact, candidates = self._index_matches(index, raw)
        appid = None
        source = None
        raw_name = None
        if len(exact) == 1:
            appid, source = exact[0], "app_list"
        elif len(exact) > 1:
            return {**base, "resolve_status": "unresolved", "candidates": [
                {"appid": a, "name": "", "source": "app_list"} for a in exact],
                "reason": "目录索引中存在多个同名条目，请指定 AppID 或从候选中选择"}

        # 3) 商店搜索（当前语言 + 英文），仅采纳归一化后精确同名且唯一的 AppID
        if appid is None:
            seen: dict[int, dict] = {}
            for lang in dict.fromkeys((self.lang, "english")):
                for item in self._search_store(raw, lang):
                    seen.setdefault(item["appid"], item)
            matches = [item for item in seen.values() if normalize(item["name"]) == normalize(raw)]
            if len(matches) == 1:
                chosen = matches[0]
                appid, source, raw_name = chosen["appid"], "store_search", chosen["name"]
            else:
                candidates = (candidates + (matches or list(seen.values())))[:8]
                return {**base, "resolve_status": "unresolved", "candidates": candidates,
                        "reason": "找到多个同名条目，请使用 AppID 指定" if len(matches) > 1
                                  else "未找到可核验的唯一精确匹配，未自动入库；请改用 AppID 或从候选中选择"}

        names = self.fetch_names(appid)
        status = "exact" if (names["name_en"] or names["name_zh"] or raw_name) else "appid_only"
        if not names["name_en"] and not names["name_zh"] and raw_name:
            # 搜索结果名称的语言由查询语言决定，不能据此断言它是中文或英文
            names["checked_at"] = _now()
        return {**base, "appid": appid, **names, "resolve_status": status, "source": source,
                "raw_name": raw_name,
                "reason": "已按官方数据源确认 AppID" if status == "exact"
                          else "AppID 已确认，但中英文名称未能补全，保留为未知"}

    def resolve_batch(self, texts: list[str]) -> list[dict]:
        """批量解析；按归一化输入去重，超出上限的部分明确标为未处理。"""
        seen: set[str] = set()
        out: list[dict] = []
        for text in texts[:MAX_BATCH]:
            key = normalize(text)
            if not key:
                continue
            if key in seen:
                continue
            seen.add(key)
            out.append(self.resolve_one(text))
        if len(texts) > MAX_BATCH:
            out.append({
                "input": "", "appid": None, "name_en": None, "name_zh": None,
                "resolve_status": "invalid", "source": None, "raw_name": None,
                "checked_at": None, "candidates": [],
                "reason": f"单次最多解析 {MAX_BATCH} 条，本次有 {len(texts) - MAX_BATCH} 条未处理",
            })
        return out
