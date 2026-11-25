"""CDK（Steam 产品激活码）批量登记与人工激活辅助。

安全与诚实原则（与仓库既有 pending_remove 先例一致）
----------------------------------------------------
* Steam 的产品激活接口没有公开官方 API；网页端 ``registerkey`` 需要登录态
  session 并带人工确认流程，自动提交既违反 Valve 服务条款精神，也缺乏
  可靠的成功核验手段。因此本模块**不实现自动提交**：
  - 用户在本机登记 CDK 明细（明文保存在本地 SQLite，不上传）；
  - 逐条「确认激活」仅做格式校验并把状态置为 ``ready``，不产生任何网络提交；
  - 激活动作由用户在 Steam 客户端 / 官方激活页完成；工具提供逐条复制入口
    与官方入口链接，不代点、不代提交。
* 状态语义严格区分：``ready``（已登记且格式通过、待人工激活）
  → ``activated``（**用户手动标记**「已在 Steam 激活成功」）/ ``invalid``（格式
  校验不通过）/ ``failed``（用户手动标记激活失败）。工具永远不自动写
  ``activated``——激活是否成功只有用户在 Steam 里能看到，不伪称成功。
* CDK 是有价凭证：不做自动重试、不把 key 写入日志（日志只出现掩码）、
  CSV 导出需用户显式点击且默认导出**掩码**值。
"""
from __future__ import annotations

import datetime as dt
import re
import threading

from . import database, logstore

# Steam CDK 常见格式：5 组、每组 5 位字母数字（如 XXXXX-XXXXX-XXXXX-XXXXX-XXXXX）。
# 组数在 2–5 之间均可合法存在（老 CD / 预载 key 可能较短）；这里按官方注册页
# 的实际接受范围校验：2–5 组、每组 3–6 位字母数字。
_CDK_RE = re.compile(r"^[A-Za-z0-9]{3,6}(-[A-Za-z0-9]{3,6}){1,4}$")

_key_lock = threading.Lock()

VALID_STATUS = ("pending", "ready", "activated", "invalid", "failed")


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def validate_format(key: str) -> tuple[bool, str]:
    """校验 CDK 格式。仅是格式判断，不代表 key 有效或未被使用。"""
    k = str(key or "").strip()
    if not k:
        return False, "激活码为空"
    if len(k) > 64:
        return False, "激活码过长（上限 64 字符）"
    if not _CDK_RE.fullmatch(k):
        return False, "格式不符合 Steam 激活码惯例（2–5 组、每组 3–6 位字母数字、连字符分隔）"
    return True, ""


def mask(key: str) -> str:
    """把激活码掩码为 ``ABCDE-•••••-•••••``：仅保留第一组与组数结构。"""
    k = str(key or "").strip()
    groups = k.split("-") if k else []
    if not groups or not groups[0]:
        return "•••"
    return "-".join([groups[0]] + ["•" * len(g) for g in groups[1:]])


def add_keys(keys: list[str], note: str = "") -> dict:
    """批量登记激活码（格式通过记 ready，非法记 invalid），不静默丢弃。"""
    out = {"added": 0, "invalid": 0, "duplicate": 0, "items": []}
    note = str(note or "")[:500]
    with _key_lock:
        with database.get_conn() as conn:
            for raw in keys:
                k = str(raw or "").strip()
                if not k:
                    continue
                ok_fmt, why = validate_format(k)
                status = "ready" if ok_fmt else "invalid"
                exists = conn.execute(
                    "SELECT 1 FROM cdk_keys WHERE key_value = ? COLLATE NOCASE", (k,)
                ).fetchone()
                if exists:
                    out["duplicate"] += 1
                    out["items"].append({"key_masked": mask(k), "status": "duplicate",
                                         "reason": "已存在，不重复登记"})
                    continue
                conn.execute(
                    "INSERT INTO cdk_keys(key_value, note, status, reason, added_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (k, note, status, why, _now(), _now()),
                )
                if ok_fmt:
                    out["added"] += 1
                else:
                    out["invalid"] += 1
                out["items"].append({"key_masked": mask(k), "status": status, "reason": why})
    logstore.add("INFO", f"CDK 登记：新增 {out['added']}，格式无效 {out['invalid']}，重复 {out['duplicate']}")
    return out


def confirm_keys(key_ids: list[int]) -> dict:
    """逐条二次确认：把 pending/ready 之外不动的条目置为 ready（格式复验）。

    这里不产生任何网络请求；ready 只表示「用户确认要在 Steam 里激活」。
    """
    out = {"confirmed": 0, "skipped": 0, "items": []}
    with _key_lock:
        with database.get_conn() as conn:
            for kid in key_ids:
                row = conn.execute("SELECT * FROM cdk_keys WHERE id = ?", (int(kid),)).fetchone()
                if not row:
                    out["skipped"] += 1
                    continue
                if row["status"] in ("activated", "failed"):
                    out["skipped"] += 1
                    out["items"].append({"id": int(kid), "key_masked": mask(row["key_value"]),
                                         "status": row["status"], "reason": "已有终态，跳过"})
                    continue
                ok_fmt, why = validate_format(row["key_value"])
                new_status = "ready" if ok_fmt else "invalid"
                conn.execute(
                    "UPDATE cdk_keys SET status = ?, reason = ?, updated_at = ? WHERE id = ?",
                    (new_status, why, _now(), int(kid)),
                )
                if ok_fmt:
                    out["confirmed"] += 1
                else:
                    out["skipped"] += 1
                out["items"].append({"id": int(kid), "key_masked": mask(row["key_value"]),
                                     "status": new_status, "reason": why})
    return out


def mark_status(key_id: int, status: str, reason: str = "") -> dict:
    """用户手动标记激活结果（activated / failed / ready）。

    activated 只能由用户显式标记——工具无法核验 Steam 侧结果，绝不自动写。
    """
    if status not in ("activated", "failed", "ready"):
        return {"ok": False, "error": "只能手动标记已激活、失败或待激活"}
    with _key_lock:
        with database.get_conn() as conn:
            row = conn.execute("SELECT id, key_value FROM cdk_keys WHERE id = ?", (int(key_id),)).fetchone()
            if not row:
                return {"ok": False, "error": "条目不存在"}
            if status in ("activated", "ready") and not validate_format(row["key_value"])[0]:
                return {"ok": False, "error": "格式无效的激活码不能标记为待激活或已激活"}
            conn.execute(
                "UPDATE cdk_keys SET status = ?, reason = ?, updated_at = ? WHERE id = ?",
                (status, reason, _now(), int(key_id)),
            )
    return {"ok": True}


def remove_key(key_id: int) -> dict:
    """删除单条登记（明文一并删除；激活结果无法撤回，仅删本机记录）。"""
    with _key_lock:
        with database.get_conn() as conn:
            cur = conn.execute("DELETE FROM cdk_keys WHERE id = ?", (int(key_id),))
            if cur.rowcount <= 0:
                return {"ok": False, "error": "条目不存在"}
    return {"ok": True}


def list_keys(status: str = "", limit: int = 500) -> dict:
    """列表接口：返回掩码 key、状态统计与分页内条目；明文仅在 reveal_key 按条返回。"""
    with database.get_conn() as conn:
        sql = "SELECT id, key_value, note, status, reason, added_at, updated_at FROM cdk_keys"
        args: list = []
        if status:
            sql += " WHERE status = ?"
            args.append(status)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(max(1, min(int(limit), 2000)))
        rows = conn.execute(sql, args).fetchall()
        counts = {r["status"]: r["n"] for r in conn.execute(
            "SELECT status, COUNT(*) AS n FROM cdk_keys GROUP BY status").fetchall()}
        items = []
        for r in rows:
            items.append({"id": r["id"], "key_masked": mask(r["key_value"]), "note": r["note"],
                          "status": r["status"], "reason": r["reason"],
                          "added_at": r["added_at"], "updated_at": r["updated_at"]})
    return {"items": items, "counts": counts, "total": len(items)}


def reveal_key(key_id: int) -> dict:
    """显式取回单条明文（用户复制到 Steam 使用）。逐条返回、带审计日志（不落 key 本身）。"""
    with database.get_conn() as conn:
        row = conn.execute("SELECT key_value, status FROM cdk_keys WHERE id = ?", (int(key_id),)).fetchone()
    if not row:
        return {"ok": False, "error": "条目不存在"}
    logstore.add("INFO", f"CDK #{key_id} 明文被取回（状态 {row['status']}），用于手动激活")
    return {"ok": True, "key": row["key_value"], "status": row["status"]}
