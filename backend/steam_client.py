"""Steam 数据客户端：拉取库、读取商店详情、校验归属，带本地缓存与 429 抛出。"""
from __future__ import annotations

import datetime as dt
import json
import re
import threading
import time

import requests
from requests.exceptions import (
    ConnectionError as ReqConnError,
    ConnectTimeout,
    HTTPError,
    SSLError,
    Timeout,
)

from . import config, database


class SteamApiError(Exception):
    """Steam 接口通用错误。"""


class RateLimited(SteamApiError):
    """命中 429，携带 Retry-After（秒，可能为 None）。"""

    def __init__(self, retry_after: float | None):
        self.retry_after = retry_after
        super().__init__("Steam 限流 (429)")


class SteamClient:
    def __init__(self, api_key: str, steamid: str, cc: str | None = None,
                 lang: str | None = None, verify_ssl: bool = True):
        self.api_key = api_key.strip()
        self.steamid = steamid.strip()
        self.cc = cc or config.DEFAULT_CC
        self.lang = lang or config.DEFAULT_LANG
        self.session = requests.Session()
        self.session.verify = verify_ssl
        self.session.headers.update({"User-Agent": "SteamToolbox/1.0 (local tool)"})
        self._ssl_fallback = False
        self._local = threading.local()

    @property
    def last_cache_hit(self) -> bool:
        return getattr(self._local, "last_cache_hit", False)

    @last_cache_hit.setter
    def last_cache_hit(self, value: bool) -> None:
        self._local.last_cache_hit = value

    @classmethod
    def from_settings(cls) -> "SteamClient":
        s = database.get_settings()
        verify_ssl = s.get("verify_ssl", "true").lower() != "false"
        return cls(s.get("api_key", ""), s.get("steamid", ""), s.get("cc"), s.get("lang"), verify_ssl)

    @staticmethod
    def fallback_header(appid: int) -> str:
        return f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/header.jpg"

    @classmethod
    def pick_cover(cls, appid: int, header_image: str | None, logo: str | None) -> str:
        return header_image or logo or cls.fallback_header(appid)

    # ---------- 底层请求 ----------

    def _do_get(self, url: str, params: dict):
        return self.session.get(url, params=params, timeout=20)

    def _get_json(self, url: str, params: dict):
        resp = None
        for attempt in range(3):  # 初次 + 2 次瞬时网络错误重试
            try:
                resp = self._do_get(url, params)
                break
            except SSLError:
                # 本机证书链缺少受信根 CA：自动降级为不校验重试一次，避免用户手动改设置
                if self.session.verify:
                    self.session.verify = False
                    self._ssl_fallback = True
                    resp = self._do_get(url, params)
                    break
                raise SteamApiError(
                    "SSL 证书校验失败：本机缺少受信任的根证书，可在「速率设置」中关闭『校验 SSL 证书』后重试"
                )
            except (ConnectTimeout, ReqConnError, Timeout):
                if attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise SteamApiError(
                    "无法连接 Steam：网络不通、被防火墙拦截或需要代理，或连接超时，请稍后重试"
                )

        if resp.status_code == 429:
            raw = resp.headers.get("Retry-After")
            retry_after = float(raw) if raw and raw.isdigit() else None
            raise RateLimited(retry_after)
        if resp.status_code == 401:
            raise SteamApiError("API Key 无效或已失效，请重新到 Steam 申请 Key 后保存")
        if resp.status_code == 403:
            raise SteamApiError("无权访问该账号资料：请检查 SteamID 是否正确、账号资料是否私密，或 Key 权限是否足够")
        try:
            resp.raise_for_status()
        except HTTPError:
            raise SteamApiError(f"Steam 接口返回错误（HTTP {resp.status_code}）")
        try:
            return resp.json()
        except ValueError:
            raise SteamApiError("Steam 返回了无法解析的内容（可能是网络拦截页或地区限制）")

    # ---------- 业务接口 ----------

    def get_country_code(self) -> str | None:
        """通过公开资料接口识别账号所在国家/地区，返回小写商店区码（如 cn）；识别不到返回 None。"""
        if not self.api_key or not self.steamid:
            return None
        data = self._get_json(
            f"{config.STEAM_API_BASE}/ISteamUser/GetPlayerSummaries/v2/",
            {"key": self.api_key, "steamids": self.steamid},
        )
        players = (data.get("response") or {}).get("players") or []
        if not players:
            return None
        cc = str(players[0].get("loccountrycode") or "").strip()
        return cc.lower() or None

    def get_owned_games(self) -> list[dict]:
        if not self.api_key or not self.steamid:
            raise SteamApiError("缺少 API Key 或 SteamID，无法拉取游戏库")
        data = self._get_json(
            f"{config.STEAM_API_BASE}/IPlayerService/GetOwnedGames/v1/",
            {
                "key": self.api_key,
                "steamid": self.steamid,
                "include_appinfo": 1,
                "include_played_free_games": 1,
            },
        )
        if not isinstance(data, dict):
            raise SteamApiError("Steam 返回内容结构异常，请稍后重试")
        response = data.get("response") or {}
        if not isinstance(response, dict):
            response = {}
        if response.get("error"):
            raise SteamApiError(f"Steam 返回错误：{response['error']}")
        return response.get("games") or []

    def get_appdetails(self, appid: int) -> dict | None:
        cached = self._cache_get(appid)
        if cached is not None:
            self.last_cache_hit = True
            return cached
        self.last_cache_hit = False
        data = self._get_json(
            f"{config.STORE_API_BASE}/appdetails",
            {
                "appids": appid,
                "cc": self.cc,
                "l": self.lang,
                "filters": "basic,price_overview,dlc,SupportedLanguages,release_date,header_image,short_description",
            },
        )
        node = data.get(str(appid)) or {}
        body = node.get("data") if node.get("success") else None
        if body is not None:
            self._cache_set(appid, body)
        return body

    def owns_app(self, appid: int) -> bool:
        """校验单个 DLC/本体是否已拥有（CheckAppOwnership）。"""
        data = self._get_json(
            f"{config.STEAM_API_BASE}/ISteamUser/CheckAppOwnership/v4/",
            {"key": self.api_key, "steamid": self.steamid, "appid": appid},
        )
        return bool(data.get("appownership", {}).get("ownsapp"))

    def search_free_games(self, pages: int = 2, count: int = 50) -> list[dict]:
        """抓取商店「免费」筛选列表，提取 appid / 名称 / 小封面。

        搜索结果不含价格与折扣，需逐个 appdetails 核定是否限时免费。
        """
        items: list[dict] = []
        seen: set[int] = set()
        for page in range(max(1, pages)):
            data = self._get_json(
                config.STORE_SEARCH_BASE,
                {
                    "query": "",
                    "start": page * count,
                    "count": count,
                    "filter": "free",
                    "cc": self.cc,
                    "l": self.lang,
                    "json": 1,
                },
            )
            for it in data.get("items", []) or []:
                logo = it.get("logo", "")
                match = re.search(r"/apps/(\d+)/", logo)
                if not match:
                    continue
                appid = int(match.group(1))
                if appid in seen:
                    continue
                seen.add(appid)
                items.append({"appid": appid, "name": it.get("name", ""), "logo": logo})
        return items

    # ---------- 本地缓存 ----------

    def _cache_ttl(self) -> float:
        try:
            return float(database.get_setting("cache_ttl_hours")) * 3600
        except (TypeError, ValueError):
            return config.CACHE_TTL_HOURS * 3600

    def _cache_get(self, appid: int) -> dict | None:
        with database.get_conn() as conn:
            row = conn.execute(
                "SELECT body, fetched_at FROM scan_cache WHERE appid = ?", (appid,)
            ).fetchone()
        if not row:
            return None
        fetched = dt.datetime.fromisoformat(row["fetched_at"])
        if (dt.datetime.now() - fetched).total_seconds() > self._cache_ttl():
            return None
        return json.loads(row["body"]) if row["body"] else None

    def _cache_set(self, appid: int, body: dict) -> None:
        now = dt.datetime.now().isoformat(timespec="seconds")
        with database.get_conn() as conn:
            conn.execute(
                "INSERT INTO scan_cache(appid, body, fetched_at) VALUES (?, ?, ?) "
                "ON CONFLICT(appid) DO UPDATE SET body = excluded.body, fetched_at = excluded.fetched_at",
                (appid, json.dumps(body, ensure_ascii=False), now),
            )
