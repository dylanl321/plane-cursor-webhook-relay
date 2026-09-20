import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import DeliveryPublic, Route, RouteCreate


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS routes (
                    id TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL,
                    cursor_webhook_url TEXT NOT NULL,
                    cursor_bearer_token TEXT NOT NULL,
                    plane_secret TEXT,
                    description TEXT NOT NULL,
                    forward_plane_headers INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS deliveries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    route_id TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    completed_at TEXT NOT NULL,
                    cursor_status INTEGER,
                    outcome TEXT NOT NULL,
                    latency_ms INTEGER NOT NULL,
                    plane_delivery_id TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_deliveries_received
                    ON deliveries(received_at DESC);
                CREATE TABLE IF NOT EXISTS delivery_keys (
                    route_id TEXT NOT NULL,
                    plane_delivery_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (route_id, plane_delivery_id)
                );
                """
            )

    def list_routes(self) -> list[Route]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM routes ORDER BY id").fetchall()
        return [self._route(row) for row in rows]

    def get_route(self, route_id: str) -> Route | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM routes WHERE id = ?", (route_id,)).fetchone()
        return self._route(row) if row else None

    def create_route(self, route: RouteCreate) -> Route:
        timestamp = now_iso()
        values = route.model_dump()
        with self._connect() as db:
            db.execute(
                """INSERT INTO routes
                (id, enabled, cursor_webhook_url, cursor_bearer_token, plane_secret,
                 description, forward_plane_headers, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    values["id"],
                    values["enabled"],
                    values["cursor_webhook_url"],
                    values["cursor_bearer_token"],
                    values["plane_secret"],
                    values["description"],
                    values["forward_plane_headers"],
                    timestamp,
                    timestamp,
                ),
            )
        created = self.get_route(route.id)
        assert created is not None
        return created

    def update_route(self, route_id: str, values: dict[str, Any]) -> Route | None:
        current = self.get_route(route_id)
        if current is None:
            return None
        if not values:
            return current
        values["updated_at"] = now_iso()
        assignments = ", ".join(f"{key} = ?" for key in values)
        with self._connect() as db:
            db.execute(
                f"UPDATE routes SET {assignments} WHERE id = ?",  # noqa: S608
                (*values.values(), route_id),
            )
        return self.get_route(route_id)

    def delete_route(self, route_id: str) -> bool:
        with self._connect() as db:
            result = db.execute("DELETE FROM routes WHERE id = ?", (route_id,))
        return result.rowcount > 0

    def add_delivery(
        self,
        *,
        route_id: str,
        received_at: str,
        completed_at: str,
        cursor_status: int | None,
        outcome: str,
        latency_ms: int,
        plane_delivery_id: str | None,
    ) -> None:
        with self._connect() as db:
            db.execute(
                """INSERT INTO deliveries
                (route_id, received_at, completed_at, cursor_status, outcome, latency_ms,
                 plane_delivery_id) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    route_id,
                    received_at,
                    completed_at,
                    cursor_status,
                    outcome,
                    latency_ms,
                    plane_delivery_id,
                ),
            )

    def claim_delivery(self, route_id: str, plane_delivery_id: str) -> bool:
        try:
            with self._connect() as db:
                db.execute(
                    """INSERT INTO delivery_keys
                    (route_id, plane_delivery_id, created_at) VALUES (?, ?, ?)""",
                    (route_id, plane_delivery_id, now_iso()),
                )
        except sqlite3.IntegrityError:
            return False
        return True

    def release_delivery(self, route_id: str, plane_delivery_id: str) -> None:
        with self._connect() as db:
            db.execute(
                "DELETE FROM delivery_keys WHERE route_id = ? AND plane_delivery_id = ?",
                (route_id, plane_delivery_id),
            )

    def list_deliveries(self, limit: int) -> list[DeliveryPublic]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM deliveries ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [DeliveryPublic(**dict(row)) for row in rows]

    @staticmethod
    def _route(row: sqlite3.Row) -> Route:
        values = dict(row)
        values["enabled"] = bool(values["enabled"])
        values["forward_plane_headers"] = bool(values["forward_plane_headers"])
        return Route(**values)
