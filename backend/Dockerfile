FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# System deps: libmagic for MIME sniffing, libpq for psycopg, curl for HEALTHCHECK
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        libmagic1 \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Non-root runtime user. Compose bind-mounts /app in dev, so the host
# bind-mount will own files in dev — that's fine, the container process just
# needs read access. In a production build (no bind mount), files are owned
# by this user at COPY time.
RUN groupadd --system app && useradd --system --gid app --home /app app \
    && chown -R app:app /app
USER app

EXPOSE 8000

# NOTE: no HEALTHCHECK here — this image is also the build context for the
# Celery worker and beat containers, which don't listen on 8000. The API's
# health probe lives on the `api` service in docker-compose.yml instead.
