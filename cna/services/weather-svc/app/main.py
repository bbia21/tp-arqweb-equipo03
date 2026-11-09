"""S3 weather-svc: pronóstico del clima con caché, timeout, reintentos e interruptor de circuito.

Reemplaza (estrangula) la llamada directa de Libre Closet a Open-Meteo.
Orden de respuesta: caché fresca -> Open-Meteo -> caché vieja -> 503 JSON.
"""
import json
import logging
from contextlib import asynccontextmanager
from datetime import date

import httpx
import redis.asyncio as redis
from fastapi import FastAPI, Query, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from .breaker import CircuitBreaker, CircuitOpenError
from .config import settings
from .forecast import BadRequest, build_params, cache_key, parse, validate
from opentelemetry import trace as otel_trace

from .tracing import SpanKind, setup_tracing, tracer
from .observability import RequestContextMiddleware, setup_logging

log = setup_logging(settings.service_name)
setup_tracing(settings.service_name)
CACHE = Counter("weather_cache_total", "Resultado de la caché", ["result"])
UPSTREAM = Counter("weather_upstream_total", "Llamadas a Open-Meteo por resultado", ["result"])

state: dict = {}
breaker = CircuitBreaker(fail_max=settings.breaker_fail_max, reset_timeout=settings.breaker_reset_seconds)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    state["redis"] = redis.from_url(settings.redis_url, decode_responses=True)
    state["http"] = httpx.AsyncClient(timeout=settings.timeout_seconds)
    log.info("weather-svc iniciado")
    yield
    await state["http"].aclose()
    await state["redis"].aclose()


app = FastAPI(title="weather-svc", version="1.0.0", lifespan=lifespan)
app.add_middleware(RequestContextMiddleware)


def _error(code: int, error: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=code, content={"error": error, "detail": detail})


async def _fetch(lat: float, lon: float, unit: str) -> dict:
    breaker.before_call()
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(settings.retries),
            wait=wait_exponential(multiplier=0.2, max=2),
            retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
            reraise=True,
        ):
            with attempt, tracer.start_as_current_span(
                "GET api.open-meteo.com/v1/forecast", kind=SpanKind.CLIENT,
                attributes={"server.address": "api.open-meteo.com",
                            "intento": attempt.retry_state.attempt_number},
            ) as span:
                response = await state["http"].get(settings.open_meteo_url, params=build_params(lat, lon, unit))
                span.set_attribute("http.response.status_code", response.status_code)
                response.raise_for_status()
                data = response.json()
    except (httpx.TransportError, httpx.HTTPStatusError):
        breaker.record_failure()
        UPSTREAM.labels(result="error").inc()
        raise
    breaker.record_success()
    UPSTREAM.labels(result="ok").inc()
    return data


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/readyz")
async def readyz():
    try:
        await state["redis"].ping()
        redis_ok = True
    except Exception:  # noqa: BLE001
        redis_ok = False
    # Open-Meteo caído no hace al servicio "no listo": puede responder desde la caché
    return JSONResponse(
        status_code=200 if redis_ok else 503,
        content={"status": "ready" if redis_ok else "not_ready", "cache": redis_ok, "circuit": breaker.state},
    )


@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/v2/weather")
async def get_weather(
    lat: float = Query(...),
    lon: float = Query(...),
    days: int = Query(default=7),
    unit: str = Query(default="celsius"),
):
    try:
        validate(lat, lon, days, unit)
    except BadRequest as exc:
        return _error(400, "bad_request", str(exc))

    key = cache_key(lat, lon, unit, date.today())
    body = {"location": {"lat": round(lat, 2), "lon": round(lon, 2)}, "unit": unit, "circuit": breaker.state}

    with tracer.start_as_current_span("redis: leer caché", attributes={"db.system": "redis"}):
        cached = await state["redis"].get(key)
    otel_trace.get_current_span().set_attribute("cache", "hit" if cached else "miss")
    if cached:
        CACHE.labels(result="hit").inc()
        return {**body, "cache": "hit", "days": parse(json.loads(cached), days)}

    CACHE.labels(result="miss").inc()
    try:
        data = await _fetch(lat, lon, unit)
    except (CircuitOpenError, httpx.TransportError, httpx.HTTPStatusError) as exc:
        stale = await state["redis"].get(f"stale:{key}")
        log.warning("Open-Meteo no disponible (%s); circuito=%s", type(exc).__name__, breaker.state)
        if stale:
            CACHE.labels(result="stale").inc()
            return {**body, "circuit": breaker.state, "cache": "stale", "days": parse(json.loads(stale), days)}
        return _error(503, "service_unavailable", "el pronóstico no está disponible en este momento")

    raw = json.dumps(data)
    await state["redis"].set(key, raw, ex=settings.cache_ttl_seconds)
    await state["redis"].set(f"stale:{key}", raw, ex=settings.stale_ttl_seconds)
    return {**body, "circuit": breaker.state, "cache": "miss", "days": parse(data, days)}
