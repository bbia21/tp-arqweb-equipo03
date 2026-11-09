"""S1 calendar-svc: consulta del calendario de outfits, alimentado por eventos."""
import asyncio
from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Query, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from . import db
from .config import settings
from .consumer import Consumer
from .handlers import to_response
from .monolith import MonolithClient
from .observability import RequestContextMiddleware, setup_logging

log = setup_logging(settings.service_name)
state: dict = {}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    state["pool"] = await db.connect(settings.database_url)
    state["monolith"] = MonolithClient(
        settings.monolith_url, settings.svc_email, settings.svc_password,
        settings.monolith_timeout_seconds, settings.monolith_verify_tls, settings.svc_password_file,
    )
    state["consumer"] = Consumer(settings.amqp_url, settings.queue, state["pool"], state["monolith"])
    consumer_task = asyncio.create_task(state["consumer"].start())
    log.info("calendar-svc iniciado")
    yield
    consumer_task.cancel()
    await state["consumer"].close()
    await state["monolith"].close()
    await state["pool"].close()


app = FastAPI(title="calendar-svc", version="1.0.0", lifespan=lifespan)
app.add_middleware(RequestContextMiddleware)


def _error(code: int, error: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=code, content={"error": error, "detail": detail})


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/readyz")
async def readyz():
    db_ok = await db.ping(state["pool"]) if "pool" in state else False
    broker_ok = bool(state.get("consumer") and state["consumer"].connected)
    ready = db_ok and broker_ok
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ready" if ready else "not_ready", "database": db_ok, "broker": broker_ok},
    )


@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/v2/calendar")
async def get_calendar(
    owner_id: int | None = Query(default=None),
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = Query(default=None),
):
    tz = ZoneInfo(settings.timezone)
    today = datetime.now(tz).date()
    start_day = from_ or today - timedelta(days=7)
    end_day = to or today + timedelta(days=7)
    if end_day < start_day:
        return _error(400, "invalid_range", "'to' tiene que ser igual o posterior a 'from'")
    start = datetime.combine(start_day, time.min, timezone.utc)
    end = datetime.combine(end_day + timedelta(days=1), time.min, timezone.utc)
    rows = await db.list_entries(state["pool"], owner_id, start, end)
    return {
        "from": start_day.isoformat(),
        "to": end_day.isoformat(),
        "count": len(rows),
        "entries": [to_response(r, settings.monolith_public_url) for r in rows],
    }


@app.get("/v2/calendar/today")
async def get_today(owner_id: int | None = Query(default=None)):
    tz = ZoneInfo(settings.timezone)
    today = datetime.now(tz).date()
    start = datetime.combine(today, time.min, timezone.utc)
    rows = await db.list_entries(state["pool"], owner_id, start, start + timedelta(days=1))
    if not rows:
        return _error(404, "not_found", "no hay outfit agendado para hoy")
    return {"date": today.isoformat(), "entries": [to_response(r, settings.monolith_public_url) for r in rows]}
