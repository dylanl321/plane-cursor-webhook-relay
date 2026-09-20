from fastapi.testclient import TestClient

from relay.app import create_app
from relay.config import Settings


def test_healthz_is_public_and_reports_ok(tmp_path):
    app = create_app(Settings(admin_api_key="test-admin-key", database_path=tmp_path / "relay.db"))

    response = TestClient(app).get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
