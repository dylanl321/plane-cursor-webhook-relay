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

- Public GitHub repository: `https://github.com/dylanl321/plane-cursor-webhook-relay`.
- Unit/API tests developed test-first; 12 tests pass with no warnings.
- Ruff formatting/lint and strict mypy pass.
- GitHub Actions CI passes, including a clean Linux Docker image build.
- TrueNAS custom app `plane-cursor-webhook-relay` is running on `10.0.0.10:8787` with a persistent named volume.
- Nginx Proxy Manager host ID 36 and Let's Encrypt certificate ID 43 expose `https://webhook-relay.home.dlewis.me`.
- Direct and TLS `/healthz` both return 200; unauthenticated admin returns 401.
- Live TLS acceptance against an external echo upstream proved raw JSON forwarding, Plane header pass-through, bearer injection, successful delivery deduplication, admin `/test`, metadata-only delivery records, and CRUD cleanup.
- A real TrueNAS stop/start cycle proved SQLite route persistence and service recovery.
- Cursor-specific acceptance remains intentionally unrun until a real Cursor webhook URL and bearer token are installed through the admin API; no credentials were supplied or committed.
