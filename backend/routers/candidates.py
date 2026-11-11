"""候选 DLC 清单、汇总、标记与 CSV 导出。"""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Query

from .. import database, exporter

router = APIRouter(prefix="/api/candidates", tags=["candidates"])

SELECT = """
SELECT c.dlc_appid, c.item_type, c.status, c.reason, c.cover_url, c.added_at, c.updated_at,
       c.ignored, c.favorite,
       d.parent_appid, d.name, d.type, d.price_initial, d.price_final,
       d.currency, d.supported_languages, d.fetched_at,
       g.name AS parent_name
FROM candidates c
LEFT JOIN dlc_items d ON d.dlc_appid = c.dlc_appid
LEFT JOIN owned_games g ON g.appid = d.parent_appid
"""


def _build_query(status: str, item_type: str, favorite: str, ignored: str, lang: str):
    sql = SELECT
    where: list[str] = []
    params: list = []
    if item_type:
        where.append("c.item_type = ?")
        params.append(item_type)
    if status:
        where.append("c.status = ?")
        params.append(status)
    else:
        where.append("c.status != 'owned'")
    if favorite == "1":
        where.append("c.favorite = 1")
    if ignored == "1":
        where.append("c.ignored = 1")
    elif ignored != "1" and ignored != "all":
        where.append("c.ignored = 0")
    if lang:
        where.append("d.supported_languages LIKE ?")
        params.append(f"%{lang}%")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY c.favorite DESC, c.updated_at DESC"
    return sql, params


@router.get("")
def list_candidates(
    status: str = Query(default=""),
    item_type: str = Query(default="dlc"),
    favorite: str = Query(default=""),
    ignored: str = Query(default=""),
    lang: str = Query(default=""),
):
    sql, params = _build_query(status, item_type, favorite, ignored, lang)
    with database.get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


@router.get("/summary")
def summary(item_type: str = Query(default="dlc")):
    sql = "SELECT status, COUNT(*) AS n FROM candidates WHERE item_type = ? GROUP BY status"
    with database.get_conn() as conn:
        rows = conn.execute(sql, [item_type]).fetchall()
    counts = {r["status"]: r["n"] for r in rows}
    return {
        "claimable": counts.get("claimable", 0),
        "owned": counts.get("owned", 0),
        "skipped": counts.get("skipped", 0),
        "unknown": counts.get("unknown", 0),
        "total": sum(counts.values()),
    }


@router.post("/{appid}/mark")
def mark(appid: int, body: dict = Body(...)):
    field = body.get("field")
    if field not in ("ignored", "favorite"):
        raise HTTPException(status_code=400, detail="field 仅支持 ignored / favorite")
    value = 1 if body.get("value") else 0
    with database.get_conn() as conn:
        cur = conn.execute(
            f"UPDATE candidates SET {field} = ? WHERE dlc_appid = ?", (value, appid)
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="候选条目不存在")
    return {"ok": True, "appid": appid, field: value}


@router.get("/export.csv")
def export_csv(
    status: str = Query(default=""),
    item_type: str = Query(default="dlc"),
    favorite: str = Query(default=""),
    ignored: str = Query(default=""),
    lang: str = Query(default=""),
):
    sql, params = _build_query(status, item_type, favorite, ignored, lang)
    with database.get_conn() as conn:
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    headers = ["AppID", "名称", "所属本体", "类型", "状态", "理由", "支持语言", "收藏", "忽略", "封面", "更新时间"]
    table = []
    for r in rows:
        table.append([
            r["dlc_appid"], r["name"], r["parent_name"], r["type"], r["status"], r["reason"],
            r["supported_languages"], "是" if r["favorite"] else "", "是" if r["ignored"] else "",
            r["cover_url"], r["updated_at"],
        ])
    return exporter.csv_response("candidates.csv", headers, table)
