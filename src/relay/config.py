import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    admin_api_key: str
    database_path: Path
    host: str = "0.0.0.0"  # noqa: S104 - container listener is intentionally network-visible
    port: int = 8787
    forward_timeout_seconds: float = 15.0
    seed_route_id: str = "nightplot-intake"
    cursor_webhook_url: str | None = None
    cursor_webhook_token: str | None = None
    plane_webhook_secret: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        admin_api_key = os.getenv("ADMIN_API_KEY", "")
        if not admin_api_key:
            raise ValueError("ADMIN_API_KEY is required")
        cursor_url = os.getenv("CURSOR_WEBHOOK_URL") or None
        cursor_token = os.getenv("CURSOR_WEBHOOK_TOKEN") or None
        if bool(cursor_url) != bool(cursor_token):
            raise ValueError("CURSOR_WEBHOOK_URL and CURSOR_WEBHOOK_TOKEN must be set together")
        return cls(
            admin_api_key=admin_api_key,
            database_path=Path(os.getenv("DATABASE_PATH", "/data/relay.db")),
            host=os.getenv("HOST", "0.0.0.0"),  # noqa: S104
            port=int(os.getenv("PORT", "8787")),
            forward_timeout_seconds=float(os.getenv("FORWARD_TIMEOUT_SECONDS", "15")),
            seed_route_id=os.getenv("SEED_ROUTE_ID", "nightplot-intake"),
            cursor_webhook_url=cursor_url,
            cursor_webhook_token=cursor_token,
            plane_webhook_secret=os.getenv("PLANE_WEBHOOK_SECRET") or None,
        )
