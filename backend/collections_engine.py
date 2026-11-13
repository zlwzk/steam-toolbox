"""Steam 库自动分类引擎（移植自独立命令行工具，剥离 CLI / 控制台横幅 / 预览网页）。

职责边界：
- 只读本机 Steam 缓存（appinfo.vdf / librarycache / cloudstorage），计算分类方案；
- 唯一联网请求为官方标签表接口，失败静默回退内置离线表；不上传任何本机数据；
- 写入前自动备份，命名空间版本号字段绝不改动；Steam 运行中拒绝写入 / 还原。

数据表（CATS / W / Q / ADULT / JP_DEV / XIANXIA_* / MANUAL / TAGS）原样见 collections_data。
"""
from __future__ import annotations

import collections
import json
import os
import random
import re
import shutil
import string
import struct
import subprocess
import time

import requests

from . import ca_store, config
from .collections_data import (
    ADULT,
    CATS,
    JP_DEV,
    MANUAL,
    Q,
    TAGS,
    W,
    XIANXIA_EN,
    XIANXIA_KW,
)

IS_WIN = os.name == "nt"
TAGLIST_API = "https://api.steampowered.com/IStoreService/GetTagList/v1/?language=schinese"

ACCOUNTID_OFFSET = 76561197960265728


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def posw(i: int) -> float:
    return 1.0 / (1.0 + i * 0.28)


# ────────────────────────────── 找 Steam 与账号 ──────────────────────────────

def find_steam(explicit: str | None = None) -> str | None:
    cands: list[str] = []
    if explicit:
        cands.append(explicit)
    if IS_WIN:
        try:
            import winreg

            for root, key in (
                (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam"),
            ):
                try:
                    with winreg.OpenKey(root, key) as k:
                        for val in ("SteamPath", "InstallPath"):
                            try:
                                cands.append(winreg.QueryValueEx(k, val)[0])
                            except OSError:
                                pass
                except OSError:
                    pass
        except ImportError:
            pass
        for d in "CDEFGH":
            cands += [rf"{d}:\Steam", rf"{d}:\Program Files (x86)\Steam", rf"{d}:\SteamLibrary"]
    else:
        home = os.path.expanduser("~")
        cands += [
            os.path.join(home, ".steam", "steam"),
            os.path.join(home, ".local", "share", "Steam"),
            os.path.join(home, "Library", "Application Support", "Steam"),
        ]
    for c in cands:
        c = os.path.normpath(c.replace("/", os.sep))
        if os.path.isdir(os.path.join(c, "userdata")) and os.path.isdir(os.path.join(c, "appcache")):
            return c
    return None


def _parse_vdf_text(path: str) -> dict:
    """极简 KeyValues 文本解析，够用来读 loginusers.vdf。"""
    try:
        txt = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return {}
    out, stack, cur = {}, [], None
    key = None
    for line in txt.splitlines():
        line = line.strip()
        if line == "{":
            node: dict = {}
            if key is not None:
                (cur if cur is not None else out)[key] = node
            stack.append(cur if cur is not None else out)
            cur, key = node, None
        elif line == "}":
            cur = stack.pop() if stack else None
        else:
            m = re.findall(r'"((?:[^"\\]|\\.)*)"', line)
            if len(m) == 1:
                key = m[0]
            elif len(m) >= 2:
                (cur if cur is not None else out)[m[0]] = m[1]
    return out


def list_accounts(steam: str) -> list[dict]:
    """返回 [{accountid, steamid64, name, timestamp, userdata_path}]，最近登录排最前。"""
    ud = os.path.join(steam, "userdata")
    users = _parse_vdf_text(os.path.join(steam, "config", "loginusers.vdf")).get("users", {}) or {}
    info: dict[str, tuple[str, str, int]] = {}
    for sid, d in users.items():
        try:
            info[str(int(sid) - ACCOUNTID_OFFSET)] = (
                sid,
                d.get("PersonaName") or d.get("AccountName") or "?",
                int(d.get("timestamp") or 0),
            )
        except (TypeError, ValueError):
            pass
    out: list[dict] = []
    if os.path.isdir(ud):
        for name in os.listdir(ud):
            p = os.path.join(ud, name)
            if not name.isdigit() or name == "0" or not os.path.isdir(p):
                continue
            sid, nick, ts = info.get(name, ("-", "(未登录过)", 0))
            if not ts:
                try:
                    ts = int(os.path.getmtime(os.path.join(p, "config")))
                except OSError:
                    ts = 0
            out.append({"accountid": name, "steamid64": sid, "name": nick,
                        "timestamp": ts, "userdata_path": p})
    out.sort(key=lambda x: -x["timestamp"])
    return out


def cloudstorage_dir(account: dict) -> str:
    return os.path.join(account["userdata_path"], "config", "cloudstorage")


# ─────────────────────────── 读 appinfo.vdf ───────────────────────────

def parse_appinfo(path: str) -> dict:
    data = open(path, "rb").read()
    magic, _universe = struct.unpack_from("<II", data, 0)
    if magic >> 8 != 0x075644:
        raise ValueError("appinfo.vdf 格式不认识，Steam 版本可能太新或太旧")
    ver = magic & 0xFF
    off, strtab = 8, None
    if ver >= 0x29:
        (stoff,) = struct.unpack_from("<q", data, off)
        off += 8
        n, = struct.unpack_from("<I", data, stoff)
        p, strtab = stoff + 4, []
        for _ in range(n):
            e = data.index(b"\x00", p)
            strtab.append(data[p:e].decode("utf-8", "replace"))
            p = e + 1

    def read_kv(pos: int, end: int):
        out: dict = {}
        while pos < end:
            t = data[pos]
            pos += 1
            if t == 0x08:
                return out, pos
            if strtab is not None:
                idx, = struct.unpack_from("<I", data, pos)
                pos += 4
                key = strtab[idx]
            else:
                e = data.index(b"\x00", pos)
                key, pos = data[pos:e].decode("utf-8", "replace"), e + 1
            if t == 0x00:
                val, pos = read_kv(pos, end)
            elif t == 0x01:
                e = data.index(b"\x00", pos)
                val, pos = data[pos:e].decode("utf-8", "replace"), e + 1
            elif t in (0x02, 0x06):
                val, = struct.unpack_from("<i", data, pos)
                pos += 4
            elif t == 0x07:
                val, = struct.unpack_from("<Q", data, pos)
                pos += 8
            else:
                raise ValueError("bad type")
            out[key] = val
        return out, pos

    apps: dict[int, dict] = {}
    hdr = 4 + 4 + 8 + 20 + 4 + (20 if ver >= 0x28 else 0)
    while off < len(data) - 4:
        appid, = struct.unpack_from("<I", data, off)
        if appid == 0:
            break
        size, = struct.unpack_from("<I", data, off + 4)
        body, nxt = off + 8, off + 8 + size
        try:
            kv, _ = read_kv(body + hdr, nxt)
            apps[appid] = kv.get("appinfo", kv)
        except Exception:
            pass
        off = nxt
    return apps


def fetch_tags() -> dict[int, str]:
    tags = {int(k): v for k, v in TAGS.items()}
    try:
        resp = requests.get(TAGLIST_API, timeout=15, verify=ca_store.bundle_path())
        resp.raise_for_status()
        for t in resp.json()["response"]["tags"]:
            tags[t["tagid"]] = t["name"]
    except Exception:  # noqa: BLE001 - 断网 / 接口异常回退内置表
        pass
    return tags


def _lang_level(sl, code: str) -> int:
    if not isinstance(sl, dict):
        return 0
    e = sl.get(code)
    if not isinstance(e, dict):
        return 0
    return 2 if e.get("full_audio") == "true" else 1


def build_games(steam: str, apps: dict, tags: dict[int, str]) -> list[dict]:
    libcache: set[str] = set()
    lc = os.path.join(steam, "appcache", "librarycache")
    if os.path.isdir(lc):
        libcache = {x for x in os.listdir(lc) if x.isdigit()}
    keep = ("game", "application", "music", "demo")
    extra = {380, 420, 340}  # 半条命 2 三部资料片在 appinfo 里被标成 tool
    out: list[dict] = []
    for aid, kv in apps.items():
        c = kv.get("common") or {}
        t = (c.get("type") or "").lower()
        if t not in keep and aid not in extra:
            continue
        if libcache and str(aid) not in libcache and t == "demo":
            continue
        st = c.get("store_tags") or {}
        tl = [tags.get(v, "") for _, v in sorted(st.items(), key=lambda x: int(x[0]))]
        cat = c.get("category") or {}
        assoc = c.get("associations") or {}
        devs = [a.get("name") for a in assoc.values()
                if isinstance(a, dict) and a.get("type") == "developer"]
        nl, sl = c.get("name_localized"), c.get("supported_languages")
        yr = 0
        if c.get("steam_release_date"):
            try:
                yr = time.gmtime(c["steam_release_date"]).tm_year
            except (ValueError, OSError, OverflowError):
                yr = 0
        out.append({
            "appid": aid, "name": c.get("name") or "", "type": t, "yr": yr,
            "cn": (nl or {}).get("schinese") if isinstance(nl, dict) else None,
            "tags": tl, "dev": devs[:2],
            "cat": sorted(int(x.split("_")[1]) for x in cat if x.startswith("category_")),
            "jp": _lang_level(sl, "japanese"), "en": _lang_level(sl, "english"),
            "nlang": len(sl) if isinstance(sl, dict) else 0,
            "inlib": str(aid) in libcache,
        })
    out.sort(key=lambda r: r["name"].lower())
    return out


# ──────────────────────────── 分类逻辑 ────────────────────────────

def _flags(r: dict) -> dict:
    dev = " ".join(r["dev"] or []).lower() + " "
    r["_T"] = [norm(t) for t in r["tags"]]
    r["_S"] = set(r["_T"])
    r["_jp"] = (
        any(j in dev for j in JP_DEV)
        or (r["jp"] == 2 and r["en"] != 2)
        or "日系角色扮演" in r["_S"]
        or ("动漫" in r["_T"][:6] and r["jp"] >= 1 and r["nlang"] <= 6)
    )
    return r


def _score(r: dict) -> dict[int, float]:
    s: dict[int, float] = {}
    for i, t in enumerate(r["_T"]):
        if not t:
            continue
        pw = posw(i)
        for cid, tw in W.items():
            if t in tw:
                s[cid] = s.get(cid, 0) + tw[t] * pw
    name = (r["name"] or "") + " " + (r["cn"] or "")
    cat = set(r["cat"])
    if r["_jp"]:
        s[2] = s.get(2, 0) + 5.0
    if any(k in name for k in XIANXIA_KW) or any(k in name.lower() for k in XIANXIA_EN):
        s[12] = s.get(12, 0) + 12
    if 20 in cat:
        s[9] = s.get(9, 0) + 9
    if r["yr"] and r["yr"] <= 2009:
        s[24] = s.get(24, 0) + 6.0
    elif r["yr"] and r["yr"] <= 2012:
        s[24] = s.get(24, 0) + 2.5
    if 1 in cat and 2 not in cat:
        s[8] = s.get(8, 0) + 6
    if r["type"] in ("application", "music"):
        s[25] = s.get(25, 0) + 30
    if r["type"] == "music":
        s[25] = s.get(25, 0) + 10
    return s


def _primary_cat(r: dict) -> int:
    if r["appid"] in MANUAL:
        return MANUAL[r["appid"]]
    if set(r["_T"][:8]) & {"视觉小说", "互动小说", "文字游戏"}:
        return 7
    if r["yr"] and r["yr"] <= 2010 and r["type"] == "game":
        return 24
    s = _score(r)
    if not s:
        return 19
    return max(s.items(), key=lambda kv: (kv[1], -kv[0]))[0]


def _memberships(r: dict, primary: int, maxcats: int) -> list[int]:
    t = r["_T"]
    name = (r["name"] or "") + " " + (r["cn"] or "")
    cand: set[int] = set()
    for cid, rules in Q.items():
        for tagset, npos in rules:
            if npos and (set(tagset) & set(t[:npos])):
                cand.add(cid)
                break
    if r["yr"] and r["yr"] <= 2010 and r["type"] == "game":
        cand.add(24)
    if r["_jp"]:
        cand.add(2)
    if 20 in set(r["cat"]):
        cand.add(9)
    if r["type"] in ("application", "music"):
        cand.add(25)
    if (any(k in name for k in XIANXIA_KW) or any(k in name.lower() for k in XIANXIA_EN)
            or (ADULT.isdisjoint(t) and {"武侠", "仙侠"} & set(t[:5]))):
        cand.add(12)
    hits = [i for i, x in enumerate(t[:4]) if x in ADULT]
    if len(hits) >= 2 or (hits and hits[0] <= 1 and len(set(t) & ADULT) >= 2):
        cand.add(28)
    s = _score(r)
    cand.discard(primary)
    rest = sorted(cand, key=lambda c: (-s.get(c, 0), c))
    return [primary] + rest[:max(0, maxcats - 1)]


def classify(games: list[dict], maxcats: int, overrides: dict | None = None) -> list[dict]:
    overrides = overrides or {}
    out: list[dict] = []
    for r in games:
        r = _flags(dict(r))
        p = _primary_cat(r)
        if p == 0:
            continue
        cats = _memberships(r, p, maxcats)
        ov = overrides.get(str(r["appid"]), overrides.get(r["appid"]))
        if ov is not None:  # [] 合法：表示不参与分类
            cats = [int(x) for x in ov if int(x) in CATS]
            if not cats:
                continue
        out.append({"id": r["appid"], "n": r["name"], "cn": r["cn"], "c": cats[0],
                    "all": cats, "y": r["yr"], "t": [x for x in r["tags"][:4] if x]})
    return out


# ──────────────────────────── 写入 / 还原 ────────────────────────────

def steam_running() -> bool:
    try:
        if IS_WIN:
            out = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq steam.exe"],
                capture_output=True, text=True, timeout=30,
            ).stdout
            return "steam.exe" in (out or "").lower()
        r = subprocess.run(["pgrep", "-x", "steam"], capture_output=True, timeout=30)
        return r.returncode == 0
    except Exception:
        return False


def _backup(cs: str) -> str:
    d = os.path.join(cs, "BACKUP-%s" % time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(d, exist_ok=True)
    for f in os.listdir(cs):
        p = os.path.join(cs, f)
        if os.path.isfile(p):
            shutil.copy2(p, d)
    return d


def last_backup(cs: str) -> str | None:
    if not os.path.isdir(cs):
        return None
    baks = sorted(d for d in os.listdir(cs)
                  if d.startswith("BACKUP-") and os.path.isdir(os.path.join(cs, d)))
    return baks[-1] if baks else None


def write_collections(cs: str, plan: list[dict], dry: bool = False):
    ns1 = os.path.join(cs, "cloud-storage-namespace-1.json")
    nsmod = os.path.join(cs, "cloud-storage-namespace-1.modified.json")
    nss = os.path.join(cs, "cloud-storage-namespaces.json")
    if not os.path.isfile(ns1):
        raise ValueError("找不到 cloud-storage-namespace-1.json：该账号可能从未打开过 Steam 库界面，先启动一次 Steam 再试")
    doc = json.load(open(ns1, encoding="utf-8"))
    members = collections.defaultdict(set)
    for g in plan:
        for c in g["all"]:
            members[c].add(g["id"])

    used = {k.split(".", 1)[1] for k, v in doc if k.startswith("user-collections.")}
    byname: dict[str, int] = {}
    for i, (k, v) in enumerate(doc):
        if k.startswith("user-collections.") and v.get("value") and not v.get("is_deleted"):
            try:
                byname[json.loads(v["value"]).get("name")] = i
            except Exception:
                pass
    # 命名空间版本由 Steam 与服务器协商，绝不改动：改了会被服务器判为冲突并回滚。
    nsver = 0
    if os.path.isfile(nss):
        try:
            for n, v in json.load(open(nss, encoding="utf-8")):
                if n == 1 and str(v).isdigit():
                    nsver = int(v)
        except Exception:
            pass
    now, rows, dirty = int(time.time()), [], []

    for num in sorted(CATS):
        name, apps = CATS[num], sorted(members.get(num, ()))
        if not apps:
            continue
        oldver = None
        if name in byname:
            i = byname[name]
            key = doc[i][0]
            old = len(json.loads(doc[i][1]["value"])["added"])
            v0 = doc[i][1].get("version")
            if str(v0).isdigit() and int(v0) <= nsver:
                oldver = str(v0)
            entry = doc[i][1] = {}
            rows.append((name, old, len(apps)))
        else:
            while True:
                cid = "uc-" + "".join(random.choice(string.ascii_letters) for _ in range(12))
                if cid not in used:
                    used.add(cid)
                    break
            key = "user-collections." + cid
            entry = {}
            doc.append([key, entry])
            rows.append((name, None, len(apps)))
        entry.update({
            "key": key, "timestamp": now,
            "value": json.dumps({"id": key.split(".", 1)[1], "name": name,
                                 "added": apps, "removed": []},
                                ensure_ascii=False, separators=(",", ":")),
            "conflictResolutionMethod": "custom",
            "strMethodId": "union-collections",
        })
        if oldver:
            entry["version"] = oldver
        dirty.append(key)

    if dry:
        return rows, None
    bak = _backup(cs)
    tmp = ns1 + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, ns1)

    # 关键：改动过的 key 写进 .modified 文件，Steam 启动时才会上传到云端。
    old_dirty: list = []
    if os.path.isfile(nsmod):
        try:
            old_dirty = [k for k in json.load(open(nsmod, encoding="utf-8")) if isinstance(k, str)]
        except Exception:
            old_dirty = []
    merged = list(dict.fromkeys(old_dirty + dirty))
    with open(nsmod, "w", encoding="utf-8") as fh:
        json.dump(merged, fh, ensure_ascii=False, separators=(",", ":"))
    return rows, bak


def restore_backup(cs: str) -> str:
    baks = sorted(d for d in os.listdir(cs)
                  if d.startswith("BACKUP-") and os.path.isdir(os.path.join(cs, d)))
    if not baks:
        raise ValueError("没有找到备份目录，无法还原")
    src = os.path.join(cs, baks[-1])
    for f in os.listdir(src):
        shutil.copy2(os.path.join(src, f), os.path.join(cs, f))
    return src


def load_overrides() -> dict:
    """读取本机自定义覆盖（my-overrides.json / overrides.json），失败忽略。"""
    ov: dict = {}
    here = config.APP_DIR
    for fname in ("my-overrides.json", "overrides.json"):
        for p in (os.path.join(config.DATA_DIR, fname), os.path.join(here, fname)):
            if not os.path.isfile(p):
                continue
            try:
                ov = json.load(open(p, encoding="utf-8-sig"))
            except Exception:
                ov = {}
            break
        if ov:
            break
    return ov


def build_plan(steam: str, account: dict, maxcats: int,
               overrides: dict | None = None) -> dict:
    """读取本机缓存并计算分类方案（不写盘）。"""
    tags = fetch_tags()
    apps = parse_appinfo(os.path.join(steam, "appcache", "appinfo.vdf"))
    games = build_games(steam, apps, tags)
    plan = classify(games, maxcats, overrides if overrides is not None else load_overrides())
    links = sum(len(g["all"]) for g in plan)
    per = collections.Counter(c for g in plan for c in g["all"])
    return {
        "cats": {str(k): v for k, v in CATS.items()},
        "games": plan,
        "who": account["name"],
        "stats": {
            "games": len(plan),
            "links": links,
            "avg": round(links / len(plan), 2) if plan else 0,
            "per_category": {str(k): per.get(k, 0) for k in sorted(CATS)},
            "tags_count": len(tags),
        },
    }
