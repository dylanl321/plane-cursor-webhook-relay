import re
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator

ROUTE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def validate_route_id(value: str) -> str:
    if not ROUTE_ID_PATTERN.fullmatch(value):
        raise ValueError("id must contain only letters, numbers, hyphens, or underscores")
    return value


def validate_webhook_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("cursor_webhook_url must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password:
        raise ValueError("cursor_webhook_url must not contain credentials")
    return value


class RouteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    enabled: bool = True
    cursor_webhook_url: str
    cursor_bearer_token: str = Field(min_length=1)
    plane_secret: str | None = None
    description: str = ""
    forward_plane_headers: bool = True

    _validate_id = field_validator("id")(validate_route_id)
    _validate_url = field_validator("cursor_webhook_url")(validate_webhook_url)


class RoutePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    cursor_webhook_url: str | None = None
    cursor_bearer_token: str | None = Field(default=None, min_length=1)
    plane_secret: str | None = None
    description: str | None = None
    forward_plane_headers: bool | None = None

    @field_validator("cursor_webhook_url")
    @classmethod
    def validate_optional_url(cls, value: str | None) -> str | None:
        return validate_webhook_url(value) if value is not None else None


class Route(RouteCreate):
    created_at: str
    updated_at: str


class RoutePublic(BaseModel):
    id: str
    enabled: bool
    cursor_webhook_url: str
    description: str
    forward_plane_headers: bool
    has_token: bool
    has_plane_secret: bool
    created_at: str
    updated_at: str

    @classmethod
    def from_route(cls, route: Route) -> "RoutePublic":
        return cls(
            id=route.id,
            enabled=route.enabled,
            cursor_webhook_url=route.cursor_webhook_url,
            description=route.description,
            forward_plane_headers=route.forward_plane_headers,
            has_token=bool(route.cursor_bearer_token),
            has_plane_secret=bool(route.plane_secret),
            created_at=route.created_at,
            updated_at=route.updated_at,
        )


class DeliveryPublic(BaseModel):
    id: int
    route_id: str
    received_at: str
    completed_at: str
    cursor_status: int | None
    outcome: str
    latency_ms: int
    plane_delivery_id: str | None


JsonDict = dict[str, Any]
