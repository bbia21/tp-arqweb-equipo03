"""Trazas distribuidas con OpenTelemetry (C3). Se exportan por OTLP/HTTP a Jaeger.

Si OTEL_EXPORTER_OTLP_ENDPOINT no está definida, los spans se crean igual pero no se envían
a ningún lado (así las pruebas y el arranque no dependen de Jaeger).
El contexto viaja en el header W3C `traceparent`: en HTTP y en los headers de los mensajes de RabbitMQ.
"""
import os

from opentelemetry import propagate, trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import SpanKind, Status, StatusCode

tracer = trace.get_tracer("libre-closet-cna")

__all__ = ["setup_tracing", "tracer", "SpanKind", "Status", "StatusCode", "extract", "inject", "current_trace_id"]


def setup_tracing(service: str) -> TracerProvider:
    provider = TracerProvider(resource=Resource.create({
        "service.name": service,
        "service.version": os.getenv("SERVICE_VERSION", "1.0.0"),
    }))
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").rstrip("/")
    if endpoint:
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces", timeout=2)))
    trace.set_tracer_provider(provider)
    return provider


def extract(carrier):
    """Contexto padre a partir de headers HTTP o de un mensaje (dict)."""
    return propagate.extract({str(k).lower(): str(v) for k, v in (carrier or {}).items()})


def inject(carrier: dict) -> dict:
    propagate.inject(carrier)
    return carrier


def current_trace_id() -> str | None:
    ctx = trace.get_current_span().get_span_context()
    return format(ctx.trace_id, "032x") if ctx.is_valid else None
