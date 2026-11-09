"""El contexto de traza que llega en un mensaje se continúa en el span del consumidor."""
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.tracing import extract, inject, tracer

exporter = InMemorySpanExporter()
provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(exporter))
trace.set_tracer_provider(provider)


def test_traceparent_viaja_en_los_headers_del_mensaje():
    with tracer.start_as_current_span("publicar en event-bridge") as padre:
        headers = inject({"x-request-id": "abc"})
    assert "traceparent" in headers
    with tracer.start_as_current_span("consumir en S1", context=extract(headers)) as hijo:
        pass
    assert hijo.get_span_context().trace_id == padre.get_span_context().trace_id
    assert hijo.parent.span_id == padre.get_span_context().span_id
