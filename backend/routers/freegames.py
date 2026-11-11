"""喜加一（限时免费本体）分区、标记与 CSV 导出。"""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Query

from .. import database, exporter

router = APIRouter(prefix="/api/freegames", tags=["freegames"])


def _build_query(status: str, favorite: str, ignored: str, lang: str):
    sql = "SELECT * FROM free_games"
    where: list[str] = []
    params: list = []
    if status:
        where.append("status = ?")
        params.append(status)
    else:
        where.append("status != 'owned'")
    if favorite == "1":
        where.append("favorite = 1")
    if ignored == "1":
        where.append("ignored = 1")
    elif ignored != "all":
        where.append("ignored = 0")
    if lang:
        where.append("supported_languages LIKE ?")
        params.append(f"%{lang}%")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY favorite DESC, fetched_at DESC"
    return sql, params


@router.get("")
def list_free_games(
    status: str = Query(default=""),
    favorite: str = Query(default=""),
    ignored: str = Query(default=""),
    lang: str = Query(default=""),
):
    sql, params = _build_query(status, favorite, ignored, lang)
    with database.get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


@router.get("/summary")
def summary():
    with database.get_conn() as conn:
        rows = conn.execute("SELECT status, COUNT(*) AS n FROM free_games GROUP BY status").fetchall()
    counts = {r["status"]: r["n"] for r in rows}
    return {
        "limited_free": counts.get("limited_free", 0),
        "permanent_free": counts.get("permanent_free", 0),
        "paid": counts.get("paid", 0),
        "demo": counts.get("demo", 0),
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
            f"UPDATE free_games SET {field} = ? WHERE appid = ?", (value, appid)
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="条目不存在")
    return {"ok": True, "appid": appid, field: value}


@router.get("/export.csv")
def export_csv(
    status: str = Query(default=""),
    favorite: str = Query(default=""),
    ignored: str = Query(default=""),
    lang: str = Query(default=""),
):
    sql, params = _build_query(status, favorite, ignored, lang)
    with database.get_conn() as conn:
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    headers = ["AppID", "名称", "类型", "状态", "折扣%", "原价", "现价", "支持语言", "收藏", "忽略", "封面", "描述", "抓取时间"]
    table = []
    for r in rows:
        table.append([
            r["appid"], r["name"], r["type"], r["status"], r["discount_percent"],
            r["price_initial"], r["price_final"], r["supported_languages"],
            "是" if r["favorite"] else "", "是" if r["ignored"] else "",
            r["cover_url"], r["description"], r["fetched_at"],
        ])
    return exporter.csv_response("free_games.csv", headers, table)
