"""Health check endpoints — verifies API + database + redis reachability."""
from django.db import connection
from ninja import Router, Schema
from redis import Redis
from redis.exceptions import RedisError

from django.conf import settings

router = Router(tags=["health"])


class HealthOut(Schema):
    status: str
    database: str
    redis: str


@router.get("", response=HealthOut)
def health(request) -> HealthOut:
    db_status = "ok"
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception as exc:  # pragma: no cover
        db_status = f"error: {exc.__class__.__name__}"

    redis_status = "ok"
    try:
        client = Redis.from_url(settings.CELERY_BROKER_URL, socket_connect_timeout=2)
        client.ping()
    except RedisError as exc:  # pragma: no cover
        redis_status = f"error: {exc.__class__.__name__}"

    overall = "ok" if db_status == "ok" and redis_status == "ok" else "degraded"
    return HealthOut(status=overall, database=db_status, redis=redis_status)
