// Trazas distribuidas con OpenTelemetry (C3). Se exportan por OTLP/HTTP a Jaeger.
// Si OTEL_EXPORTER_OTLP_ENDPOINT no está definida, los spans se crean pero no se envían.
// El contexto viaja en el header W3C "traceparent" de cada mensaje de RabbitMQ.
const { trace, context, propagation, SpanKind, SpanStatusCode } = require('@opentelemetry/api');
const { NodeTracerProvider } = require('@opentelemetry/sdk-trace-node');
const { BatchSpanProcessor } = require('@opentelemetry/sdk-trace-base');
const { OTLPTraceExporter } = require('@opentelemetry/exporter-trace-otlp-http');
const { resourceFromAttributes } = require('@opentelemetry/resources');

let provider;

function setup(serviceName) {
  const endpoint = (process.env.OTEL_EXPORTER_OTLP_ENDPOINT || '').replace(/\/$/, '');
  const spanProcessors = endpoint
    ? [new BatchSpanProcessor(new OTLPTraceExporter({ url: `${endpoint}/v1/traces`, timeoutMillis: 2000 }))]
    : [];
  provider = new NodeTracerProvider({
    resource: resourceFromAttributes({
      'service.name': serviceName,
      'service.version': process.env.SERVICE_VERSION || '1.0.0',
    }),
    spanProcessors,
  });
  provider.register(); // contexto con AsyncLocalStorage + propagador W3C traceparent
  return provider;
}

const tracer = () => trace.getTracer('libre-closet-cna');

// Ejecuta fn dentro de un span nuevo (hijo del contexto dado o del activo) y lo cierra al final.
async function inSpan(name, options, fn, parent = context.active()) {
  return tracer().startActiveSpan(name, options, parent, async (span) => {
    try {
      return await fn(span);
    } catch (err) {
      span.recordException(err);
      span.setStatus({ code: SpanStatusCode.ERROR, message: err.message });
      throw err;
    } finally {
      span.end();
    }
  });
}

const inject = (headers = {}) => {
  propagation.inject(context.active(), headers);
  return headers;
};
const extract = (headers = {}) => propagation.extract(context.active(), headers);

function currentTraceId() {
  const ctx = trace.getSpan(context.active())?.spanContext();
  return ctx && trace.isSpanContextValid(ctx) ? ctx.traceId : undefined;
}

async function shutdown() {
  if (provider) await provider.shutdown().catch(() => {});
}

module.exports = { setup, inSpan, inject, extract, currentTraceId, shutdown, SpanKind, SpanStatusCode };
