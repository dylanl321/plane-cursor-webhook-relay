from fastapi.testclient import TestClient

from relay.app import create_app
from relay.config import Settings

ADMIN = {"Authorization": "Bearer test-admin-key"}


def client(tmp_path) -> TestClient:
    return TestClient(
        create_app(Settings(admin_api_key="test-admin-key", database_path=tmp_path / "relay.db"))
    )


def route_payload() -> dict[str, object]:
    return {
        "id": "nightplot-intake",
        "enabled": True,
        "cursor_webhook_url": "https://api2.cursor.sh/automations/webhook/test-uuid",
        "cursor_bearer_token": "cursor-secret",
        "plane_secret": "plane-secret",
        "description": "Nightplot intake",
        "forward_plane_headers": True,
    }


def test_admin_requires_valid_bearer_or_x_admin_key(tmp_path):
    c = client(tmp_path)
    assert c.get("/admin/routes").status_code == 401
    assert c.get("/admin/routes", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert c.get("/admin/routes", headers={"X-Admin-Key": "test-admin-key"}).status_code == 200


def test_routes_crud_persists_and_redacts_secrets(tmp_path):
    db = tmp_path / "relay.db"
    c = client(tmp_path)
    created = c.post("/admin/routes", headers=ADMIN, json=route_payload())
    assert created.status_code == 201
    assert created.json()["has_token"] is True
    assert created.json()["has_plane_secret"] is True
    assert "cursor_bearer_token" not in created.text
    assert '"plane_secret"' not in created.text
    assert "cursor-secret" not in created.text
    assert "plane-secret" not in created.text

    duplicate = c.post("/admin/routes", headers=ADMIN, json=route_payload())
    assert duplicate.status_code == 409

    recreated = TestClient(create_app(Settings(admin_api_key="test-admin-key", database_path=db)))
    listed = recreated.get("/admin/routes", headers=ADMIN)
    assert listed.status_code == 200
    assert [route["id"] for route in listed.json()] == ["nightplot-intake"]

    patched = recreated.patch(
        "/admin/routes/nightplot-intake",
        headers=ADMIN,
        json={"enabled": False, "description": "updated"},
    )
    assert patched.status_code == 200
    assert patched.json()["enabled"] is False
    assert patched.json()["description"] == "updated"
    assert patched.json()["has_token"] is True

    fetched = recreated.get("/admin/routes/nightplot-intake", headers=ADMIN)
    assert fetched.status_code == 200
    assert fetched.json()["id"] == "nightplot-intake"

    deleted = recreated.delete("/admin/routes/nightplot-intake", headers=ADMIN)
    assert deleted.status_code == 204
    assert recreated.get("/admin/routes/nightplot-intake", headers=ADMIN).status_code == 404


def test_patch_can_rotate_and_clear_secrets(tmp_path):
    c = client(tmp_path)
    c.post("/admin/routes", headers=ADMIN, json=route_payload())

    rotated = c.patch(
        "/admin/routes/nightplot-intake",
        headers=ADMIN,
        json={"cursor_bearer_token": "new-token", "plane_secret": None},
    )

    assert rotated.status_code == 200
    assert rotated.json()["has_token"] is True
    assert rotated.json()["has_plane_secret"] is False

    for field in (
        "enabled",
        "cursor_webhook_url",
        "cursor_bearer_token",
        "description",
        "forward_plane_headers",
    ):
        rejected = c.patch("/admin/routes/nightplot-intake", headers=ADMIN, json={field: None})
        assert rejected.status_code == 422, field


def test_route_id_and_webhook_url_are_validated(tmp_path):
    c = client(tmp_path)
    bad_id = route_payload() | {"id": "not allowed"}
    bad_url = route_payload() | {"cursor_webhook_url": "file:///etc/passwd"}
    assert c.post("/admin/routes", headers=ADMIN, json=bad_id).status_code == 422
    assert c.post("/admin/routes", headers=ADMIN, json=bad_url).status_code == 422
