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

from . import config, database, logstore


class SteamApiError(Exception):
    """Steam 接口通用错误。

    status_code 为对应 HTTP 状态码；连接失败 / 响应无法解析等无状态码场景为 None。
    """

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class RateLimited(SteamApiError):
    """命中 429，携带 Retry-After（秒，可能为 None）。"""

    def __init__(self, retry_after: float | None):
        self.retry_after = retry_after
        super().__init__("Steam 限流 (429)")


class StoreBlocked(SteamApiError):
    """商店域名被网络 / 地区 / 反爬整体拦截（Akamai Access Denied 403 或拦截页）。

    与单条无数据不同：这类错误通常是当前出口 IP 被拦，应在扫描层快速熔断并
    提示用户检查网络 / 代理，而不是逐条慢速重试把清单全部标成未知。
    """


class SteamClient:
    def __init__(self, api_key: str, steamid: str, cc: str | None = None,
                 lang: str | None = None, verify_ssl: bool = True):
        self.api_key = api_key.strip()
        self.steamid = steamid.strip()
        self.cc = cc or config.DEFAULT_CC
        self.lang = lang or config.DEFAULT_LANG
        self.session = requests.Session()
        self.session.verify = verify_ssl
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": "https://store.steampowered.com/",
        })
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
            except SSLError as exc:
                raise SteamApiError(
                    "SSL 证书校验失败：请先检查系统时间、代理证书及受信任的根证书。"
                    "如需自行承担安全风险，可在高级设置中显式关闭证书校验。"
                ) from exc
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
            raise SteamApiError("API Key 无效或已失效，请重新到 Steam 申请 Key 后保存", 401)
        if resp.status_code == 403:
            if "store.steampowered.com" in url:
                raise StoreBlocked(
                    "商店接口被当前网络 / 地区拦截（403 Access Denied）：请检查网络、"
                    "切换可用代理或更换网络后重试；官方账号接口不受影响"
                )
            raise SteamApiError("无权访问该账号资料：请检查 SteamID 是否正确、账号资料是否私密，或 Key 权限是否足够", 403)
        try:
            resp.raise_for_status()
        except HTTPError:
            raise SteamApiError(f"Steam 接口返回错误（HTTP {resp.status_code}）", resp.status_code)
        try:
            return resp.json()
        except ValueError:
            text = resp.text or ""
            if "store.steampowered.com" in url and ("Access Denied" in text or "AkamaiGHost" in text):
                raise StoreBlocked(
                    "商店接口被当前网络 / 地区拦截（返回拦截页）：请检查网络、"
                    "切换可用代理或更换网络后重试"
                )
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
        return self.get_appdetails_batch([appid]).get(appid)

    # 合批接口被拒时允许降级为逐条请求的状态码；401/403 属鉴权或授权问题，
    # 逐条重试同样会失败，不降级以免放大请求量。
    _DEGRADABLE_STATUS = {400, 500, 502, 503, 504}

    def get_appdetails_batch(self, appids: list[int]) -> dict[int, dict | None]:
        """批量读取商店详情。appdetails 接口支持逗号分隔多 appid，一次请求取一批，
        相比逐条请求可显著减少往返；缓存命中的条目直接跳过，不再发请求。

        返回 {appid: 详情体 | None}；单条无数据为 None，整批被拦截则抛 StoreBlocked。

        部分网络出口对「多 AppID 合批」返回 HTTP 400 / 5xx，此时本批次自动降级为
        逐条请求；429 限流、403 整体拦截、401 鉴权失败等全局信号仍向上抛出。
        """
        uniq = [int(a) for a in dict.fromkeys(appids) if a]
        result: dict[int, dict | None] = {}
        pending: list[int] = []
        cached = self._cache_get_many(uniq)
        for appid in uniq:
            if appid in cached:
                result[appid] = cached[appid]
            else:
                pending.append(appid)
        self.last_cache_hit = bool(uniq) and not pending

        batch_size = config.APPDETAILS_BATCH_SIZE
        for i in range(0, len(pending), batch_size):
            chunk = pending[i:i + batch_size]
            bodies = self._fetch_chunk(chunk)
            result.update(bodies)
        return result

    def _fetch_chunk(self, chunk: list[int]) -> dict[int, dict | None]:
        """拉取一批详情；合批被可降级错误拒绝时退化为逐条请求。"""
        try:
            return self._fetch_batch(chunk)
        except SteamApiError as exc:
            if not self._degradable(exc):
                raise
            logstore.add(
                "WARN",
                f"批量详情接口返回 {exc.status_code or '异常'}，已降级为逐条请求（{len(chunk)} 个）",
            )

        out: dict[int, dict | None] = {}
        body_map: dict[int, dict] = {}
        for appid in chunk:
            try:
                body = self._fetch_single(appid)
            except (RateLimited, StoreBlocked):
                raise
            except SteamApiError:
                body = None
            out[appid] = body
            if body is not None:
                body_map[appid] = body
        if body_map:
            self._cache_set_many(body_map)
        return out

    @classmethod
    def _degradable(cls, exc: SteamApiError) -> bool:
        """该错误是否值得在批次层退化为逐条请求。

        限流（429）与商店整体拦截（403/拦截页）属全局信号，逐条同样会失败，
        不降级；其余按状态码判断，无状态码的连接 / 解析异常允许降级一次。
        """
        if isinstance(exc, (RateLimited, StoreBlocked)):
            return False
        return exc.status_code is None or exc.status_code in cls._DEGRADABLE_STATUS

    def _fetch_batch(self, chunk: list[int]) -> dict[int, dict | None]:
        """一次合批请求整个 chunk，解析后写缓存。"""
        data = self._get_json(
            f"{config.STORE_API_BASE}/appdetails",
            {
                "appids": ",".join(str(a) for a in chunk),
                "cc": self.cc,
                "l": self.lang,
                "filters": "basic,price_overview,dlc,SupportedLanguages,release_date,header_image,short_description",
            },
        )
        return self._parse_appdetails(data, chunk)

    def _fetch_single(self, appid: int) -> dict | None:
        """单个 AppID 的详情请求（合批降级后的兜底路径）。"""
        data = self._get_json(
            f"{config.STORE_API_BASE}/appdetails",
            {
                "appids": str(appid),
                "cc": self.cc,
                "l": self.lang,
                "filters": "basic,price_overview,dlc,SupportedLanguages,release_date,header_image,short_description",
            },
        )
        return self._parse_appdetails(data, [appid]).get(appid)

    def _parse_appdetails(self, data: dict, chunk: list[int]) -> dict[int, dict | None]:
        """把 appdetails 返回体按 chunk 解析为 {appid: 详情体 | None}，命中条目写缓存。"""
        result: dict[int, dict | None] = {}
        body_map: dict[int, dict] = {}
        for appid in chunk:
            node = data.get(str(appid)) or {}
            body = node.get("data") if node.get("success") else None
            result[appid] = body
            if body is not None:
                body_map[appid] = body
        if body_map:
            self._cache_set_many(body_map)
        return result

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

    def _cache_get_many(self, appids: list[int]) -> dict[int, dict | None]:
        """批量查缓存，返回未过期的条目；过期 / 缺失的不在结果中。"""
        if not appids:
            return {}
        placeholders = ",".join("?" for _ in appids)
        out: dict[int, dict | None] = {}
        ttl = self._cache_ttl()
        with database.get_conn() as conn:
            rows = conn.execute(
                f"SELECT appid, body, fetched_at FROM scan_cache WHERE appid IN ({placeholders})",
                appids,
            ).fetchall()
        now = dt.datetime.now()
        for row in rows:
            try:
                fetched = dt.datetime.fromisoformat(row["fetched_at"])
                if (now - fetched).total_seconds() > ttl:
                    continue
                out[row["appid"]] = json.loads(row["body"]) if row["body"] else None
            except (ValueError, TypeError):
                continue
        return out

    def _cache_set_many(self, bodies: dict[int, dict]) -> None:
        if not bodies:
            return
        now = dt.datetime.now().isoformat(timespec="seconds")
        rows = [
            (appid, json.dumps(body, ensure_ascii=False), now)
            for appid, body in bodies.items()
        ]
        with database.get_conn() as conn:
            conn.executemany(
                "INSERT INTO scan_cache(appid, body, fetched_at) VALUES (?, ?, ?) "
                "ON CONFLICT(appid) DO UPDATE SET body = excluded.body, fetched_at = excluded.fetched_at",
                rows,
            )
