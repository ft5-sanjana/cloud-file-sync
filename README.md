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
- **M1** — Auth (register, login, JWT, refresh cookie)
- **M2** — Storage layer + upload (B2, validation, quota, Celery)
- **M3** — List, delete, download, signed URLs, overwrite
- **M4** — Dashboard UI (upload, list, search, preview, delete)
- **M5** — Hardening (security pass, audit logs, docs)

## Environment variables

See `.env.example` for the full list with defaults.

## Notes

- Files are **never public**. Download and preview go through short-lived signed URLs issued by the backend.
- Storage keys are UUID-based (`users/{user_id}/{uuid}.{ext}`); user-supplied filenames are never used as object keys.
- MIME type is sniffed server-side via `python-magic`; client-supplied `Content-Type` is not trusted.
- Per-user quota is enforced transactionally to prevent race conditions between concurrent uploads.
