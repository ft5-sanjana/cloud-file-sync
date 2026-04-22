# Cloud File Sync

Secure web app for authenticated users to upload, download, preview, search, and sync private files with Backblaze B2.

## Stack

- **Frontend:** Next.js 15 (App Router), TypeScript, Tailwind, Shadcn UI
- **Backend:** Django 5 + Django Ninja
- **Database:** PostgreSQL 16
- **Async:** Redis + Celery
- **Storage:** Backblaze B2 (S3-compatible API)
- **Dev:** Docker Compose

## Project structure

```
cloud-file-sync/
├── frontend/        # Next.js app
├── backend/         # Django API + Celery worker
├── docker-compose.yml
├── .env.example
└── README.md
```

## Prerequisites

- Docker + Docker Compose
- A Backblaze B2 bucket (private) and an application key with read/write access to it

## Setup

```bash
cp .env.example .env
# Edit .env — at minimum set DJANGO_SECRET_KEY and your B2 credentials
docker compose up --build
```

On first run Compose will:
1. Start Postgres and Redis and wait for healthchecks
2. Install backend Python deps and run Django migrations
3. Install frontend npm deps and start the Next.js dev server
4. Start the Celery worker

## URLs

| Service | URL |
|---|---|
| Frontend | http://localhost:3000 |
| Backend API | http://localhost:8000/api |
| API health | http://localhost:8000/api/health |
| Web health | http://localhost:3000/api/health |
| OpenAPI docs | http://localhost:8000/api/docs |
| Django admin | http://localhost:8000/admin |

## M0 acceptance

```bash
docker compose up
curl http://localhost:8000/api/health
# → {"status":"ok","database":"ok","redis":"ok"}
curl http://localhost:3000/api/health
# → {"status":"ok","service":"web"}
```

## Roadmap

- **M0** — Scaffold ✅
- **M1** — Auth (register, login, JWT, refresh cookie) ✅
- **M2** — Storage layer + upload (B2, validation, quota, Celery) ✅
- **M3** — List, delete, download, signed URLs, overwrite ✅
- **M4** — Dashboard UI (upload, list, search, preview, delete) ✅
- **M5** — Hardening (security headers, rate limits, audit logs, docs) ✅

## Environment variables

See `.env.example` for the full list with defaults.

## Notes

- Files are **never public**. Download and preview go through short-lived signed URLs issued by the backend.
- Storage keys are UUID-based (`users/{user_id}/{uuid}.{ext}`); user-supplied filenames are never used as object keys.
- MIME type is sniffed server-side via `python-magic`; client-supplied `Content-Type` is not trusted.
- Per-user quota is enforced transactionally to prevent race conditions between concurrent uploads.

## Security

What's in place out of the box:

- **Auth** — JWT access tokens (15 min) + refresh cookie (HttpOnly, SameSite=Lax, 7 days). Refresh tokens rotate on use and the previous one is blacklisted. Access tokens are never persisted client-side beyond memory.
- **Rate limits** — per-IP on `/api/auth/register` (10/h) and `/api/auth/login` (5/m); per-user on `POST /api/files` (30/h) and `GET /api/files/{id}/signed-url` (120/h). Implemented via `django-ratelimit` with Redis as the shared store.
- **Authorization** — every file endpoint filters by `owner=request.user`. Cross-tenant access attempts return 404, not 403, so existence isn't leaked.
- **Security headers** (via `apps.common.middleware.SecurityHeadersMiddleware`):
  - `Content-Security-Policy` restricting Django-served surfaces (admin, Swagger) to self + the jsdelivr CDN required by Ninja's Swagger UI. The Next.js SPA is served on a separate origin — it is not gated by this CSP.
  - `Cross-Origin-Opener-Policy: same-origin`, `Cross-Origin-Resource-Policy: same-origin`.
  - `Permissions-Policy` denies camera/mic/geolocation/payment/usb.
  - Django's built-in `SecurityMiddleware` provides HSTS, nosniff, and referrer policy (all configured in `prod.py`).
- **Request correlation** — every response carries an `X-Request-ID` header (echoed from the client if safe, else UUID4). The same ID is stamped onto every log line so a user-reported issue can be traced end-to-end.
- **Audit log** — `apps.files.models.AuditLog` records every upload, download/preview signature, and delete with the acting user and file metadata. Viewable under `/admin/files/auditlog/`.
- **Upload defences** — size cap (100 MB default), extension allow-list, server-side MIME sniffing, SHA-256 checksum computed during streaming, storage key is UUID-based (never user-supplied).
- **Transport** — HSTS, `SECURE_SSL_REDIRECT`, and secure/HTTP-only session & CSRF cookies are enabled in the `prod` settings module. Dev disables these so you can run over plain HTTP on localhost.
- **Runtime** — backend container runs as a non-root user (`app`) and ships with a `HEALTHCHECK` that probes `/api/health`.

Known accepted tradeoffs:

- `script-src 'unsafe-inline'` is present because Next.js App Router hydration requires inline scripts. Not applied to API JSON responses.
- Swagger UI at `/api/docs` loads from `cdn.jsdelivr.net`. In a production deploy that doesn't expose Swagger, override `CSP` via a settings module to drop the CDN.
- The dev stack uses Django's `runserver` for fast reloads. See **Production deployment** below for the gunicorn override.

## Production deployment

This repo ships a Compose stack tuned for local dev. For production:

1. **Settings module** — set `DJANGO_SETTINGS_MODULE=config.settings.prod` (enables HSTS, SSL redirect, secure cookies; requires `DJANGO_ALLOWED_HOSTS` and a real `DJANGO_SECRET_KEY`).
2. **App server** — replace `python manage.py runserver 0.0.0.0:8000` in the `api` service command with:
   ```
   gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3 --timeout 120 --access-logfile -
   ```
   `gunicorn` is already in `requirements.txt`. Run `collectstatic` at build time and serve `/static/` through nginx or equivalent in front of gunicorn.
3. **Secrets** — move `DJANGO_SECRET_KEY`, `B2_APPLICATION_KEY`, and DB credentials out of `.env` into the deploy platform's secret store.
4. **TLS termination** — front the API with a TLS-terminating proxy (nginx, Caddy, cloud load balancer). Keep `SECURE_PROXY_SSL_HEADER` aligned with what the proxy sets.
5. **Frontend** — `npm run build && npm start` instead of `npm run dev`. Set `API_UPSTREAM_URL` and `NEXT_PUBLIC_*` as appropriate for your environment.
6. **Swagger** — consider gating `/api/docs` behind auth or removing it from the production URL conf (and tighten CSP accordingly).
7. **Observability** — the `X-Request-ID` header + `rid=...` log prefix are already there; point your log shipper at stdout.
