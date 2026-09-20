import pytest
from fastapi.testclient import TestClient

from relay.app import create_app
from relay.config import Settings

ADMIN = {"Authorization": "Bearer admin-secret-value"}


def test_settings_require_admin_key(monkeypatch, tmp_path):
    monkeypatch.delenv("ADMIN_API_KEY", raising=False)
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "relay.db"))

    with pytest.raises(ValueError, match="ADMIN_API_KEY"):
        Settings.from_env()


def test_seed_route_is_created_only_on_first_boot(monkeypatch, tmp_path):
    monkeypatch.setenv("ADMIN_API_KEY", "admin-secret-value")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "relay.db"))
    monkeypatch.setenv("CURSOR_WEBHOOK_URL", "https://api2.cursor.sh/automations/webhook/seed-uuid")
    monkeypatch.setenv("CURSOR_WEBHOOK_TOKEN", "seed-token")
    settings = Settings.from_env()

    first = TestClient(create_app(settings))
    route = first.get("/admin/routes/nightplot-intake", headers=ADMIN)
    assert route.status_code == 200
    assert route.json()["has_token"] is True

    first.patch(
        "/admin/routes/nightplot-intake",
        headers=ADMIN,
        json={"description": "managed remotely"},
    )
    monkeypatch.setenv("CURSOR_WEBHOOK_TOKEN", "changed-env-token")
    second = TestClient(create_app(Settings.from_env()))
    route_after_restart = second.get("/admin/routes/nightplot-intake", headers=ADMIN)
    assert route_after_restart.json()["description"] == "managed remotely"
