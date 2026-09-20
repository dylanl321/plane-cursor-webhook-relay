import hashlib
import hmac
import json

import httpx
from fastapi.testclient import TestClient

from relay.app import create_app
from relay.config import Settings

ADMIN = {"Authorization": "Bearer test-admin-key"}


def build_client(tmp_path, handler) -> TestClient:
    transport = httpx.MockTransport(handler)
    return TestClient(
        create_app(
            Settings(admin_api_key="test-admin-key", database_path=tmp_path / "relay.db"),
            forward_transport=transport,
        )
    )


def create_route(client: TestClient, *, secret: str | None = None, enabled: bool = True) -> None:
    response = client.post(
        "/admin/routes",
        headers=ADMIN,
        json={
            "id": "nightplot-intake",
            "enabled": enabled,
            "cursor_webhook_url": "https://api2.cursor.sh/automations/webhook/test-uuid",
            "cursor_bearer_token": "cursor-secret",
            "plane_secret": secret,
            "description": "Nightplot intake",
            "forward_plane_headers": True,
        },
    )
    assert response.status_code == 201


def test_plane_webhook_forwards_raw_body_headers_and_injected_authorization(tmp_path):
    seen: dict[str, object] = {}

    def cursor(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.content
        seen["headers"] = dict(request.headers)
        return httpx.Response(
            202, content=b'{"accepted":true}', headers={"content-type": "application/json"}
        )

    c = build_client(tmp_path, cursor)
    create_route(c)
    raw = b'{ "event": "workitem.created", "exact": true }\n'
    response = c.post(
        "/hooks/plane/nightplot-intake",
        content=raw,
        headers={
            "content-type": "application/json",
            "authorization": "Bearer attacker-value",
            "x-plane-event": "workitem.created",
            "x-plane-delivery": "delivery-123",
            "x-plane-signature": "unsigned",
            "x-ignored": "do-not-forward",
        },
    )

    assert response.status_code == 202
    assert response.content == b'{"accepted":true}'
    assert seen["body"] == raw
    headers = seen["headers"]
    assert isinstance(headers, dict)
    assert headers["authorization"] == "Bearer cursor-secret"
    assert headers["x-plane-event"] == "workitem.created"
    assert headers["x-plane-delivery"] == "delivery-123"
    assert headers["x-plane-signature"] == "unsigned"
    assert "x-ignored" not in headers

    deliveries = c.get("/admin/deliveries?limit=50", headers=ADMIN).json()
    assert len(deliveries) == 1
    assert deliveries[0]["route_id"] == "nightplot-intake"
    assert deliveries[0]["cursor_status"] == 202
    assert deliveries[0]["plane_delivery_id"] == "delivery-123"
    assert "cursor-secret" not in json.dumps(deliveries)


def test_signature_is_verified_against_raw_body(tmp_path):
    calls = 0

    def cursor(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(204)

    c = build_client(tmp_path, cursor)
    create_route(c, secret="plane-secret")  # noqa: S106 - non-production test fixture
    body = b'{"hello":"world"}'
    signature = hmac.new(b"plane-secret", body, hashlib.sha256).hexdigest()

    assert c.post("/hooks/plane/nightplot-intake", content=body).status_code == 401
    assert (
        c.post(
            "/hooks/plane/nightplot-intake",
            content=body,
            headers={"X-Plane-Signature": "bad"},
        ).status_code
        == 401
    )
    valid = c.post(
        "/hooks/plane/nightplot-intake",
        content=body,
        headers={"X-Plane-Signature": signature},
    )
    assert valid.status_code == 204
    assert calls == 1


def test_missing_disabled_and_upstream_timeout_are_safe(tmp_path):
    def timeout(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    c = build_client(tmp_path, timeout)
    assert c.post("/hooks/plane/missing", content=b"{}").status_code == 404
    create_route(c, enabled=False)
    assert c.post("/hooks/plane/nightplot-intake", content=b"{}").status_code == 503
    c.patch("/admin/routes/nightplot-intake", headers=ADMIN, json={"enabled": True})
    assert c.post("/hooks/plane/nightplot-intake", content=b"{}").status_code == 504


def test_successful_plane_delivery_id_is_deduplicated(tmp_path):
    calls = 0

    def cursor(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"ok": True})

    c = build_client(tmp_path, cursor)
    create_route(c)
    headers = {"X-Plane-Delivery": "same-delivery"}
    first = c.post("/hooks/plane/nightplot-intake", content=b"{}", headers=headers)
    second = c.post("/hooks/plane/nightplot-intake", content=b"{}", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == {"status": "duplicate_ignored"}
    assert calls == 1


def test_admin_test_endpoint_sends_synthetic_plane_payload(tmp_path):
    seen: dict[str, object] = {}

    def cursor(request: httpx.Request) -> httpx.Response:
        seen["json"] = json.loads(request.content)
        seen["headers"] = dict(request.headers)
        return httpx.Response(201, json={"created": True})

    c = build_client(tmp_path, cursor)
    create_route(c, secret="plane-secret")  # noqa: S106 - non-production test fixture
    response = c.post("/admin/routes/nightplot-intake/test", headers=ADMIN)

    assert response.status_code == 200
    result = response.json()
    assert result["cursor_status"] == 201
    assert result["cursor_body"] == {"created": True}
    assert seen["json"]["event"] == "relay.test"
    assert seen["headers"]["authorization"] == "Bearer cursor-secret"
