"""全局配置与默认速率参数。

所有速率数值均为可在设置页调整的默认值；Steam 未公开统一阈值，
这里采用保守的社区经验值，核心原则：低频、随机、可退避、遇阻即停。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Steam 工具助手"
APP_VERSION = "1.2.5"
# 内部构建号：随每次发版递增，用于排查「外部版号相同但构建不同」的问题；前端在关于/调试信息中可见。
BUILD_NUMBER = 2026111205

# 开发环境：工程根目录；PyInstaller 打包后：可写数据目录取 exe 同级，只读资源取解包目录
if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
    RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
else:
    APP_DIR = Path(__file__).resolve().parent.parent
    RESOURCE_DIR = APP_DIR

BASE_DIR = APP_DIR


def _writable_dir(path: Path) -> bool:
    """探测目录能否创建并写入（exe 落在 Program Files 等受保护目录时可能不可写）。"""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


# 数据目录优先 exe 同级；打包后若该目录只读/无权限，回退到用户本地目录，避免写库失败导致保存报错
_data_candidates = [APP_DIR / "data"]
if getattr(sys, "frozen", False):
    _local_appdata = os.environ.get("LOCALAPPDATA")
    if _local_appdata:
        _data_candidates.append(Path(_local_appdata) / "SteamToolbox" / "data")
DATA_DIR = next((c for c in _data_candidates if _writable_dir(c)), _data_candidates[-1])
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "claimer.db"

# 商店区与语言
DEFAULT_CC = "cn"
DEFAULT_LANG = "schinese"

# 商店区由后端依据账号公开资料自动识别，不再开放手动填写；语言可在下拉框选择。
# l= 参数代码 → 展示名（前端下拉与后端白名单共用同一组代码）
LANG_OPTIONS: dict[str, str] = {
    "schinese": "简体中文",
    "tchinese": "繁体中文",
    "english": "英语",
    "japanese": "日语",
    "koreana": "韩语",
    "russian": "俄语",
    "german": "德语",
    "french": "法语",
    "spanish": "西班牙语",
    "portuguese": "葡萄牙语",
    "italian": "意大利语",
    "polish": "波兰语",
    "turkish": "土耳其语",
    "arabic": "阿拉伯语",
    "thai": "泰语",
    "vietnamese": "越南语",
}

# 抓取阶段（盘点/读数据）
FETCH_CONCURRENCY = 4            # 抓取并发线程数；商店详情接口限流相对宽松，过高易触发 429
FETCH_DELAY_MIN = 0.3            # 每个未命中缓存批次请求的最小间隔（秒）
FETCH_DELAY_MAX = 0.8            # 每个未命中缓存批次请求的最大间隔（秒）
APPDETAILS_BATCH_SIZE = 10       # 单次 appdetails 请求合并的 appid 数量，减少往返
CACHE_TTL_HOURS = 24             # appdetails 本地缓存有效期

# 领取阶段（MVP 暂未启用自动领取，参数先落库预留）
CLAIM_HOURLY_LIMIT = 30          # 每小时领取上限（社区硬顶约 50/h，主动留余量）
CLAIM_DELAY_MIN = 8.0            # 单个领取动作最小间隔（秒）
CLAIM_DELAY_MAX = 20.0           # 单个领取动作最大间隔（秒）
CLAIM_BATCH_SIZE = 5             # 每批数量（5-10）
BATCH_REST_MIN = 120.0           # 批间休息最小（秒）
BATCH_REST_MAX = 300.0           # 批间休息最大（秒）
MAX_RETRIES = 2                  # 单项失败重试次数

# 接口地址
STEAM_API_BASE = "https://api.steampowered.com"
STORE_API_BASE = "https://store.steampowered.com/api"
STORE_SEARCH_BASE = "https://store.steampowered.com/search/results"

DEFAULT_SETTINGS: dict[str, str] = {
    "api_key": "",
    "steamid": "",
    "cc": DEFAULT_CC,
    "lang": DEFAULT_LANG,
    "fetch_delay_min": str(FETCH_DELAY_MIN),
    "fetch_delay_max": str(FETCH_DELAY_MAX),
    "fetch_concurrency": str(FETCH_CONCURRENCY),
    "cache_ttl_hours": str(CACHE_TTL_HOURS),
    "claim_hourly_limit": str(CLAIM_HOURLY_LIMIT),
    "claim_delay_min": str(CLAIM_DELAY_MIN),
    "claim_delay_max": str(CLAIM_DELAY_MAX),
    "claim_batch_size": str(CLAIM_BATCH_SIZE),
    "batch_rest_min": str(BATCH_REST_MIN),
    "batch_rest_max": str(BATCH_REST_MAX),
    "max_retries": str(MAX_RETRIES),
    "auto_claim": "false",       # 默认人工勾选后再领
    "verify_ssl": "false",       # 是否校验 SSL 证书；本机缺受信 CA 时默认关闭，代码遇证书错误也会自动降级重试
    "free_game_pages": "2",      # 喜加一搜索抓取页数（每页 50）
    "claim_headless": "false",   # 领取浏览器是否无头（首次登录建议有头）
    "browser_channel": "msedge", # 登录/领取浏览器：msedge（Edge）/ chrome / chromium（自带）
    "auto_scan": "false",        # 定时巡检开关
    "scan_interval_minutes": "360",
    "scan_kind": "both",         # dlc / freegame / both
    "notify_webhook": "",        # 完成通知 webhook（Bark / Server酱 / 通用 JSON）
    "notify_on_done": "true",
    # 创意工坊批量订阅节奏（移植自原扩展保守默认）
    "ws_delay_min": "2.5",       # 单项间隔最小（秒）
    "ws_delay_max": "5.0",       # 单项间隔最大（秒）
    "ws_batch_size": "10",        # 每批数量
    "ws_cooldown_enabled": "true",
    "ws_cooldown_min": "20",      # 批间休息最小（秒）
    "ws_cooldown_max": "45",      # 批间休息最大（秒）
    "ws_max_retries": "3",        # 单项失败重试次数
    "ws_max_pages": "20",         # 自动翻页上限（1–100）
    # 库清理默认筛选
    "cleaner_unit": "hour",       # 时长单位：minute / hour
    "cleaner_exclude_delisted": "exclude",  # keep 不排除 / exclude 排除下架 / only 仅看下架
}
