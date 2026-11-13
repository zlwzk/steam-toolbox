"""Local-only HTTP safeguards against DNS rebinding and browser cross-site requests.

The desktop application has no remote user accounts. Only loopback hosts and
its own UI (or the Vite development UI) may call its API from a browser.
"""
from __future__ import annotations

import re

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.responses import Response

_LOCAL_HOST_RE = re.compile(r"^(?:127\.0\.0\.1|localhost|\[::1\])(?::\d{1,5})?$", re.I)
_ALLOWED_ORIGINS = {
    f"http://{host}:{port}"
    for host in ("localhost", "127.0.0.1", "[::1]")
    for port in (8000, 5173)
}


def reject_unsafe_request(request: Request) -> Response | None:
    """Return 403 for untrusted Host/Origin/Fetch-Site; otherwise return None.

    Scripts without an Origin header remain compatible. Browsers send Origin
    for mutating requests and Sec-Fetch-Site for cross-site requests.
    """
    host = request.headers.get("host", "")
    if not _LOCAL_HOST_RE.fullmatch(host):
        return JSONResponse({"detail": "仅允许本机访问"}, status_code=403)
    origin = request.headers.get("origin")
    if origin is not None and origin.lower() not in _ALLOWED_ORIGINS:
        return JSONResponse({"detail": "拒绝非本机页面的请求"}, status_code=403)
    if request.url.path.startswith("/api/") and request.headers.get("sec-fetch-site", "").lower() == "cross-site":
        return JSONResponse({"detail": "拒绝跨站请求"}, status_code=403)
    return None


def add_security_headers(request: Request, response: Response) -> Response:
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response
