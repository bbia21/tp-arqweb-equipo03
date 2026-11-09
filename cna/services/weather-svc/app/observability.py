"""Logs JSON a stdout, propagación de X-Request-ID y métricas Prometheus (requisitos B2)."""
import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone

from prometheus_client import Counter, Histogram
from starlette.middleware.base import BaseHTTPMiddleware

from opentelemetry import context as otel_context, trace as otel_trace

from .tracing import SpanKind, Status, StatusCode, current_trace_id, extract, tracer

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

HTTP_REQUESTS = Counter("http_requests_total", "Peticiones HTTP por ruta y código", ["route", "code"])
HTTP_LATENCY = Histogram(
    "http_request_duration_seconds",
    "Latencia de las peticiones HTTP",
    ["route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
)


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str):
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname.lower(),
            "service": self.service,
            "request_id": getattr(record, "request_id", None) or request_id_var.get(),
            "message": record.getMessage(),
        }
        trace_id = current_trace_id()
        if trace_id:
            entry["trace_id"] = trace_id  # permite saltar del log en Loki a la traza en Jaeger
        extra = getattr(record, "extra_fields", None)
        if extra:
            entry.update(extra)
        if record.exc_info:
            entry["error"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def setup_logging(service: str) -> logging.Logger:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    # uvicorn usa sus propios loggers: que pasen por el mismo formato
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers = [handler]
        logging.getLogger(name).propagate = False
    logging.getLogger("uvicorn.access").disabled = True
    return logging.getLogger(service)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Lee o genera X-Request-ID, lo devuelve en la respuesta y mide cada petición."""

    async def dispatch(self, request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        token = request_id_var.set(request_id)
        route = request.url.path
        start = time.perf_counter()
        code = 500
        traced = route not in ("/metrics", "/healthz", "/readyz")
        span = tracer.start_span(
            f"{request.method} {route}", context=extract(request.headers), kind=SpanKind.SERVER,
            attributes={"http.request.method": request.method, "url.path": route, "request_id": request_id},
        ) if traced else None
        span_token = None
        if span is not None:
            span_token = otel_context.attach(otel_trace.set_span_in_context(span))
        try:
            response = await call_next(request)
            code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            HTTP_REQUESTS.labels(route=route, code=str(code)).inc()
            HTTP_LATENCY.labels(route=route).observe(time.perf_counter() - start)
            if route not in ("/metrics", "/healthz", "/readyz"):
                logging.getLogger("http").info(
                    "%s %s %s", request.method, route, code,
                    extra={"extra_fields": {"duration_ms": round((time.perf_counter() - start) * 1000, 1)}},
                )
            request_id_var.reset(token)
            if span is not None:
                span.set_attribute("http.response.status_code", code)
                if code >= 500:
                    span.set_status(Status(StatusCode.ERROR))
                span.end()
                otel_context.detach(span_token)
