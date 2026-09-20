# Plane → Cursor Webhook Relay

A small, server-to-server FastAPI service that accepts Plane webhooks, preserves the raw body and relevant Plane headers, and forwards them to Cursor with the required `Authorization: Bearer ...` header. A secured admin API manages routes and inspects metadata-only delivery history without SSH.

## Why this exists

Plane CE webhooks cannot add arbitrary HTTP headers. Cursor webhook automations require:

```http
Authorization: Bearer <CURSOR_WEBHOOK_KEY>
```

A direct Plane → Cursor POST therefore returns `401 Missing Authorization header`. The relay injects that header without exposing the Cursor token to Plane or source control.

## Features

- `POST /hooks/plane/{routeId}` forwards the **unchanged raw body**.
- Passes `Content-Type`, `X-Plane-Signature`, `X-Plane-Delivery`, and `X-Plane-Event` when enabled.
- Always overwrites inbound `Authorization` with the route's Cursor bearer token.
- Optional Plane HMAC-SHA256 verification over the raw request bytes.
- SQLite-backed route configuration and delivery metadata.
- Successful `X-Plane-Delivery` IDs are claimed atomically and deduplicated; failed deliveries remain retryable.
- Admin authentication via `Authorization: Bearer <ADMIN_API_KEY>` or `X-Admin-Key`.
- No CORS middleware, no unauthenticated API docs, and no secret values in API responses or structured delivery logs.
- Non-root, read-only container with all Linux capabilities dropped.

## Run with Docker Compose

```bash
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"
# Put the generated value in .env as ADMIN_API_KEY.
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:8787/healthz
```

Persistent state lives in the `relay-data` volume. For off-LAN access, put the service behind TLS (for example Nginx Proxy Manager) and do not expose port 8787 directly to the internet.

### Optional first-boot seed

Set both values before the first start:

```dotenv
CURSOR_WEBHOOK_URL=https://api2.cursor.sh/automations/webhook/<uuid>
CURSOR_WEBHOOK_TOKEN=<Cursor routine webhook key>
```

This creates `nightplot-intake` only if that ID does not exist. Later environment changes never overwrite a route managed through the admin API. `PLANE_WEBHOOK_SECRET` is optional, and `SEED_ROUTE_ID` changes the default ID.

## Point Plane at the relay

Create or edit the Plane webhook URL:

```text
https://<relay-host>/hooks/plane/nightplot-intake
```

For this deployment the intended URL is:

```text
https://webhook-relay.home.dlewis.me/hooks/plane/nightplot-intake
```

If Plane's SSRF protection rejects private destinations, use the TLS hostname routed through the LAN reverse proxy or attach the relay to a Docker network Plane can resolve. Do not bypass Plane's guard globally.

Plane signs the exact raw request body with HMAC-SHA256. If `plane_secret` is configured, the relay compares the lowercase hex digest to `X-Plane-Signature` before forwarding.

## Admin API

```bash
export BASE_URL='https://webhook-relay.home.dlewis.me'
export ADMIN_API_KEY='<admin key>'
export ADMIN_HEADER="Authorization: Bearer $ADMIN_API_KEY"
```

### Create a route

```bash
curl --fail-with-body -X POST "$BASE_URL/admin/routes" \
  -H "$ADMIN_HEADER" \
  -H 'Content-Type: application/json' \
  -d '{
    "id": "nightplot-intake",
    "enabled": true,
    "cursor_webhook_url": "https://api2.cursor.sh/automations/webhook/<uuid>",
    "cursor_bearer_token": "<Cursor routine webhook key>",
    "plane_secret": null,
    "description": "Nightplot → nightplot Plane intake webhook",
    "forward_plane_headers": true
  }'
```

### List and inspect routes

```bash
curl --fail-with-body "$BASE_URL/admin/routes" -H "$ADMIN_HEADER"
curl --fail-with-body "$BASE_URL/admin/routes/nightplot-intake" -H "$ADMIN_HEADER"
```

Responses redact both secrets and expose only `has_token` and `has_plane_secret` booleans.

### Update or rotate secrets

```bash
curl --fail-with-body -X PATCH "$BASE_URL/admin/routes/nightplot-intake" \
  -H "$ADMIN_HEADER" \
  -H 'Content-Type: application/json' \
  -d '{"cursor_bearer_token":"<new key>","enabled":true}'
```

Set `plane_secret` to `null` to clear it. A route's Cursor token cannot be cleared because forwarding would no longer work; delete or disable the route instead.

### Test a route

```bash
curl --fail-with-body -X POST \
  "$BASE_URL/admin/routes/nightplot-intake/test" \
  -H "$ADMIN_HEADER"
```

The relay sends a synthetic `relay.test` payload and returns `cursor_status` plus the parsed Cursor response body. This endpoint is admin-only and does not require a Plane signature.

### Recent deliveries

```bash
curl --fail-with-body "$BASE_URL/admin/deliveries?limit=50" -H "$ADMIN_HEADER"
```

Only route ID, timestamps, outcome, latency, Cursor status, and Plane delivery ID are stored. Request bodies and secret values are never included.

### Delete a route

```bash
curl --fail-with-body -X DELETE \
  "$BASE_URL/admin/routes/nightplot-intake" \
  -H "$ADMIN_HEADER"
```

You may use `X-Admin-Key: $ADMIN_API_KEY` instead of the bearer header, but `Authorization: Bearer ...` is the recommended handoff contract.

## Local development

```bash
uv venv
uv pip install --python .venv/Scripts/python.exe -e '.[dev]'  # Windows
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m mypy
```

On Linux/macOS, use `.venv/bin/python` instead.

## API behavior

| Endpoint | Auth | Behavior |
|---|---|---|
| `GET /healthz` | None | Liveness |
| `POST /hooks/plane/{routeId}` | Optional Plane HMAC per route | Forward to Cursor |
| `GET /admin/routes` | Admin key | List redacted routes |
| `GET /admin/routes/{id}` | Admin key | Get redacted route |
| `POST /admin/routes` | Admin key | Create route |
| `PATCH /admin/routes/{id}` | Admin key | Update route fields/secrets |
| `DELETE /admin/routes/{id}` | Admin key | Delete route |
| `POST /admin/routes/{id}/test` | Admin key | Synthetic forwarding test |
| `GET /admin/deliveries?limit=50` | Admin key | Recent metadata-only log |

Forwarding timeout defaults to 15 seconds. Cursor status, body, and `Content-Type` are returned to Plane. Timeouts return 504; network failures return 502; disabled routes return 503.

## Security notes

- Never commit `.env`, Cursor tokens, Plane secrets, or the admin key.
- Use HTTPS whenever the admin API crosses a trusted host boundary.
- Restrict the origin port with host firewall/VLAN rules when possible; TLS at Nginx Proxy Manager does not protect a directly reachable origin by itself.
- URL credentials and non-HTTP(S) Cursor destinations are rejected.
- The bearer comparison uses constant-time comparison.
- Cursor tokens and Plane secrets are currently stored in the SQLite database as application secrets. Protect the Docker volume and include it in encrypted backups.

## License

MIT
