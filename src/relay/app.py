import hashlib
import hmac
import json
import logging
import sqlite3
from time import perf_counter
from typing import Any
from uuid import uuid4

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status

from .config import Settings
from .models import DeliveryPublic, Route, RouteCreate, RoutePatch, RoutePublic
from .store import Store, now_iso

logger = logging.getLogger("relay.delivery")
PLANE_HEADERS = ("content-type", "x-plane-signature", "x-plane-delivery", "x-plane-event")


def create_app(
    settings: Settings,
    *,
    forward_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    app = FastAPI(title="Plane Cursor Webhook Relay", docs_url=None, redoc_url=None)
    app.state.settings = settings
    store = Store(settings.database_path)
    app.state.store = store
    if (
        settings.cursor_webhook_url
        and settings.cursor_webhook_token
        and store.get_route(settings.seed_route_id) is None
    ):
        store.create_route(
            RouteCreate(
                id=settings.seed_route_id,
                cursor_webhook_url=settings.cursor_webhook_url,
                cursor_bearer_token=settings.cursor_webhook_token,
                plane_secret=settings.plane_webhook_secret,
                description="Seeded from environment on first boot",
            )
        )

    async def require_admin(
        authorization: str | None = Header(default=None),
        x_admin_key: str | None = Header(default=None),
    ) -> None:
        bearer = None
        if authorization and authorization.startswith("Bearer "):
            bearer = authorization[7:]
        supplied = x_admin_key if x_admin_key is not None else bearer
        if supplied is None or not hmac.compare_digest(supplied, settings.admin_api_key):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid admin API key",
                headers={"WWW-Authenticate": "Bearer"},
            )

    def require_route(route_id: str) -> Route:
        route = store.get_route(route_id)
        if route is None:
            raise HTTPException(status_code=404, detail="route not found")
        return route

    async def send_to_cursor(
        route: Route,
        body: bytes,
        inbound_headers: Request | None,
        *,
        delivery_id: str | None,
        verify_signature: bool,
        deduplicate: bool,
    ) -> httpx.Response:
        received_at = now_iso()
        started = perf_counter()
        claimed = False

        if not route.enabled:
            raise HTTPException(status_code=503, detail="route disabled")

        if verify_signature and route.plane_secret:
            supplied = inbound_headers.headers.get("x-plane-signature") if inbound_headers else None
            expected = hmac.new(
                route.plane_secret.encode("utf-8"), body, hashlib.sha256
            ).hexdigest()
            if supplied is None or not hmac.compare_digest(supplied, expected):
                raise HTTPException(status_code=401, detail="invalid Plane signature")

        if deduplicate and delivery_id:
            claimed = store.claim_delivery(route.id, delivery_id)
            if not claimed:
                return httpx.Response(200, json={"status": "duplicate_ignored"})

        headers: dict[str, str] = {}
        if inbound_headers and route.forward_plane_headers:
            headers.update(
                {
                    name: inbound_headers.headers[name]
                    for name in PLANE_HEADERS
                    if name in inbound_headers.headers
                }
            )
        headers["authorization"] = f"Bearer {route.cursor_bearer_token}"
        headers.setdefault("content-type", "application/json")

        cursor_status: int | None = None
        outcome = "forwarded"
        try:
            async with httpx.AsyncClient(
                transport=forward_transport,
                timeout=settings.forward_timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = await client.post(
                    route.cursor_webhook_url, content=body, headers=headers
                )
            cursor_status = response.status_code
            if not 200 <= response.status_code < 300 and claimed and delivery_id:
                store.release_delivery(route.id, delivery_id)
        except httpx.TimeoutException as exc:
            outcome = "timeout"
            if claimed and delivery_id:
                store.release_delivery(route.id, delivery_id)
            raise HTTPException(status_code=504, detail="Cursor request timed out") from exc
        except httpx.RequestError as exc:
            outcome = "upstream_error"
            if claimed and delivery_id:
                store.release_delivery(route.id, delivery_id)
            raise HTTPException(status_code=502, detail="Cursor request failed") from exc
        finally:
            completed_at = now_iso()
            latency_ms = round((perf_counter() - started) * 1000)
            store.add_delivery(
                route_id=route.id,
                received_at=received_at,
                completed_at=completed_at,
                cursor_status=cursor_status,
                outcome=outcome,
                latency_ms=latency_ms,
                plane_delivery_id=delivery_id,
            )
            logger.info(
                json.dumps(
                    {
                        "routeId": route.id,
                        "status": cursor_status,
                        "latencyMs": latency_ms,
                        "deliveryId": delivery_id,
                        "outcome": outcome,
                    },
                    separators=(",", ":"),
                )
            )
        return response

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/hooks/plane/{route_id}")
    async def plane_webhook(route_id: str, request: Request) -> Response:
        route = require_route(route_id)
        body = await request.body()
        delivery_id = request.headers.get("x-plane-delivery")
        cursor = await send_to_cursor(
            route,
            body,
            request,
            delivery_id=delivery_id,
            verify_signature=True,
            deduplicate=True,
        )
        content_type = cursor.headers.get("content-type")
        headers = {"content-type": content_type} if content_type else None
        return Response(content=cursor.content, status_code=cursor.status_code, headers=headers)

    @app.get("/admin/routes", dependencies=[Depends(require_admin)])
    async def list_routes() -> list[RoutePublic]:
        return [RoutePublic.from_route(route) for route in store.list_routes()]

    @app.get("/admin/routes/{route_id}", dependencies=[Depends(require_admin)])
    async def get_route(route_id: str) -> RoutePublic:
        return RoutePublic.from_route(require_route(route_id))

    @app.post(
        "/admin/routes",
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_admin)],
    )
    async def create_route(payload: RouteCreate) -> RoutePublic:
        try:
            route = store.create_route(payload)
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="route already exists") from exc
        return RoutePublic.from_route(route)

    @app.patch("/admin/routes/{route_id}", dependencies=[Depends(require_admin)])
    async def patch_route(route_id: str, payload: RoutePatch) -> RoutePublic:
        route = store.update_route(route_id, payload.model_dump(exclude_unset=True))
        if route is None:
            raise HTTPException(status_code=404, detail="route not found")
        return RoutePublic.from_route(route)

    @app.delete(
        "/admin/routes/{route_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[Depends(require_admin)],
    )
    async def delete_route(route_id: str) -> Response:
        if not store.delete_route(route_id):
            raise HTTPException(status_code=404, detail="route not found")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post("/admin/routes/{route_id}/test", dependencies=[Depends(require_admin)])
    async def test_route(route_id: str) -> dict[str, Any]:
        route = require_route(route_id)
        delivery_id = f"relay-test-{uuid4()}"
        payload = {
            "event": "relay.test",
            "action": "test",
            "delivery_id": delivery_id,
            "data": {"message": "Synthetic test from Plane Cursor Webhook Relay"},
        }
        cursor = await send_to_cursor(
            route,
            json.dumps(payload, separators=(",", ":")).encode(),
            None,
            delivery_id=delivery_id,
            verify_signature=False,
            deduplicate=False,
        )
        try:
            body: Any = cursor.json()
        except ValueError:
            body = cursor.text
        return {"cursor_status": cursor.status_code, "cursor_body": body}

    @app.get("/admin/deliveries", dependencies=[Depends(require_admin)])
    async def list_deliveries(limit: int = 50) -> list[DeliveryPublic]:
        if limit < 1 or limit > 500:
            raise HTTPException(status_code=422, detail="limit must be between 1 and 500")
        return store.list_deliveries(limit)

    return app
