# Live Implementation Record

## Goal

Deploy a secure Plane → Cursor webhook relay on TrueNAS and expose it at `webhook-relay.home.dlewis.me` through Nginx Proxy Manager.

## Architecture

```text
Plane CE
  └─ POST /hooks/plane/{routeId}
       └─ FastAPI relay on TrueNAS :8787
            ├─ SQLite route + delivery metadata volume
            ├─ optional X-Plane-Signature verification
            └─ POST to Cursor with injected Authorization: Bearer token

Nightplot intake / Grok Bot
  └─ TLS + ADMIN_API_KEY
       └─ /admin/routes CRUD, /test, /admin/deliveries
```

## Decisions

- Python 3.13, FastAPI, HTTPX, and stdlib SQLite: small, boring stack.
- Admin bearer auth and optional `X-Admin-Key`; bearer is the supported handoff default.
- Admin docs disabled and CORS absent by default.
- Secret fields never leave admin responses; only presence booleans are returned.
- Successful Plane delivery IDs are atomically deduplicated while failed attempts remain retryable.
- Local TrueNAS image build from uploaded, committed source avoids a public registry dependency.

## Validation log

- GitHub repository created as private: `dylanl321/plane-cursor-webhook-relay`.
- Unit/API tests developed test-first; 12 tests passing before packaging.
- Remaining: static gates, container build/smoke, TrueNAS deployment, NPM TLS host, live acceptance.
