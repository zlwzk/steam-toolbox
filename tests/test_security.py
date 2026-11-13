"""No Steam credentials or live network access required."""
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.security import add_security_headers, reject_unsafe_request


def client():
    app = FastAPI()

    @app.middleware("http")
    async def guard(request: Request, call_next):
        blocked = reject_unsafe_request(request)
        if blocked is not None:
            return blocked
        return add_security_headers(request, await call_next(request))

    @app.get("/api/health")
    def health():
        return {"ok": True}

    @app.post("/api/operation")
    def operation():
        return {"ok": True}

    return TestClient(app, base_url="http://127.0.0.1:8000")


def test_local_same_origin_works():
    c = client()
    r = c.post("/api/operation", headers={"origin": "http://127.0.0.1:8000"})
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-frame-options"] == "DENY"


def test_dev_vite_origin_works():
    assert client().post("/api/operation", headers={"origin": "http://localhost:5173"}).status_code == 200


def test_reject_foreign_origin_and_null_origin():
    c = client()
    assert c.post("/api/operation", headers={"origin": "https://evil.example"}).status_code == 403
    assert c.post("/api/operation", headers={"origin": "null"}).status_code == 403
    assert c.post("/api/operation", headers={"origin": "http://localhost:8001"}).status_code == 403


def test_reject_dns_rebinding_and_cross_site():
    c = client()
    assert c.get("/api/health", headers={"host": "attack.example"}).status_code == 403
    assert c.get("/api/health", headers={"host": "127.0.0.1.evil.example"}).status_code == 403
    assert c.post("/api/operation", headers={"sec-fetch-site": "cross-site"}).status_code == 403


def test_loopback_cli_requests_without_origin_work():
    assert client().post("/api/operation").status_code == 200
