"""CSV 导出工具：带 UTF-8 BOM，便于 Excel 直接打开不乱码。"""
from __future__ import annotations

import csv
import io

from fastapi import Response


def csv_response(filename: str, headers: list[str], rows: list[list]) -> Response:
    buf = io.StringIO()
    buf.write("\ufeff")  # UTF-8 BOM
    writer = csv.writer(buf)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(row)
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
