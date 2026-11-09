// S2 wear-stats-svc: consume closet.calendar.* de stats.q y lleva la cuenta de usos por outfit.
const tracing = require('./tracing');

tracing.setup('wear-stats-svc');
const Fastify = require('fastify');
const amqp = require('amqplib');
const Redis = require('ioredis');
const pino = require('pino');
const client = require('prom-client');
const { trace } = require('@opentelemetry/api');
const { randomUUID } = require('node:crypto');
const { wornDelta, InvalidEvent, APPLY_SCRIPT, PROCESSED_TTL_SECONDS, keysFor } = require('./logic');

const config = {
  port: Number(process.env.PORT || 8000),
  redisUrl: process.env.REDIS_URL || 'redis://stats-db:6379/0',
  amqpUrl: process.env.AMQP_URL || 'amqp://guest:guest@rabbitmq:5672',
  queue: process.env.QUEUE || 'stats.q',
  exchange: process.env.EXCHANGE || 'closet.events',
  publishWorn: process.env.PUBLISH_WORN !== 'false',
  // Solo para el experimento X3: espera entre aplicar el evento y confirmarlo (ack),
  // para poder matar el proceso justo en ese momento. En operación normal es 0.
  ackDelayMs: Number(process.env.ACK_DELAY_MS || 0),
};

// Logs JSON: timestamp, level, service, request_id, message
const log = pino({
  base: { service: 'wear-stats-svc' },
  messageKey: 'message',
  timestamp: () => `,"timestamp":"${new Date().toISOString()}"`,
  formatters: { level: (label) => ({ level: label }) },
});

// Métricas
const register = new client.Registry();
client.collectDefaultMetrics({ register });
const httpRequests = new client.Counter({ name: 'http_requests_total', help: 'Peticiones HTTP', labelNames: ['route', 'code'], registers: [register] });
const httpDuration = new client.Histogram({ name: 'http_request_duration_seconds', help: 'Latencia HTTP', labelNames: ['route'], buckets: [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1], registers: [register] });
const eventsConsumed = new client.Counter({ name: 'events_consumed_total', help: 'Eventos consumidos', labelNames: ['type', 'result'], registers: [register] });

const state = { brokerConnected: false };
const redis = new Redis(config.redisUrl, { maxRetriesPerRequest: 3 });
redis.defineCommand('applyWorn', { numberOfKeys: 3, lua: APPLY_SCRIPT });

// Continúa la traza que empezó el event-bridge (header traceparent del mensaje)
async function handle(channel, publishChannel, msg) {
  const headers = msg.properties.headers || {};
  return tracing.inSpan(`consumir ${msg.properties.type || 'desconocido'}`, {
    kind: tracing.SpanKind.CONSUMER,
    attributes: {
      'messaging.system': 'rabbitmq',
      'messaging.destination.name': config.queue,
      'messaging.message.id': String(msg.properties.messageId || ''),
      'messaging.rabbitmq.redelivered': Boolean(msg.fields.redelivered),
      request_id: String(headers['x-request-id'] || '-'),
    },
  }, (span) => handleInSpan(channel, publishChannel, msg, span), tracing.extract(headers));
}

async function handleInSpan(channel, publishChannel, msg, span) {
  const requestId = (msg.properties.headers && msg.properties.headers['x-request-id']) || '-';
  const type = msg.properties.type || 'desconocido';
  try {
    const event = JSON.parse(msg.content.toString());
    const { delta, outfitId, wornAt } = wornDelta(event);
    const applied = await tracing.inSpan('redis: aplicar uso (Lua, idempotente)', { attributes: { 'db.system': 'redis', delta } },
      () => redis.applyWorn(
        ...keysFor(event.event_id, outfitId ?? 'none'),
        PROCESSED_TTL_SECONDS, delta, String(outfitId ?? ''), wornAt || '',
      ));
    if (applied === 1 && delta > 0 && config.publishWorn) {
      const out = {
        event_id: randomUUID(), type: 'stats.outfit.worn', version: '1',
        occurred_at: new Date().toISOString(), request_id: requestId,
        payload: { outfit_id: outfitId, worn_at: wornAt },
      };
      await tracing.inSpan(`publicar ${out.type}`, { kind: tracing.SpanKind.PRODUCER }, async () => {
        publishChannel.publish(config.exchange, out.type, Buffer.from(JSON.stringify(out)), {
          persistent: true, contentType: 'application/json', messageId: out.event_id, type: out.type,
          headers: tracing.inject({ 'x-request-id': requestId }),
        });
        await publishChannel.waitForConfirms();
      });
    }
    if (config.ackDelayMs > 0) {
      log.warn({ request_id: requestId, event_id: event.event_id }, `evento aplicado; ack en ${config.ackDelayMs} ms (X3)`);
      await new Promise((r) => setTimeout(r, config.ackDelayMs));
    }
    channel.ack(msg);
    const result = applied === 1 ? 'processed' : 'duplicate';
    span.setAttribute('resultado', result);
    eventsConsumed.inc({ type, result });
    log.info({ request_id: requestId, type, event_id: event.event_id, delta, result, trace_id: tracing.currentTraceId() }, `evento ${result}`);
  } catch (err) {
    if (err instanceof InvalidEvent || err instanceof SyntaxError) {
      channel.nack(msg, false, false); // directo a la DLQ
      span.setStatus({ code: tracing.SpanStatusCode.ERROR, message: 'enviado a la DLQ' });
      eventsConsumed.inc({ type, result: 'dead_lettered' });
      log.error({ request_id: requestId, type, err: err.message }, 'evento inválido enviado a la DLQ');
    } else {
      channel.nack(msg, false, true); // se reintenta; tras 5 intentos va a la DLQ
      span.setStatus({ code: tracing.SpanStatusCode.ERROR, message: 'se reintenta' });
      eventsConsumed.inc({ type, result: 'retry' });
      log.error({ request_id: requestId, type, err: err.message }, 'error transitorio, se reintenta');
    }
  }
}

async function startConsumer() {
  for (;;) {
    try {
      const connection = await amqp.connect(config.amqpUrl);
      const channel = await connection.createChannel();
      const publishChannel = await connection.createConfirmChannel();
      await channel.prefetch(10);
      await channel.checkQueue(config.queue); // la crea setup-topology
      connection.on('close', () => {
        state.brokerConnected = false;
        log.error('se cerró la conexión con RabbitMQ; reintentando');
        setTimeout(startConsumer, 2000);
      });
      connection.on('error', (err) => log.error({ err: err.message }, 'error en RabbitMQ'));
      await channel.consume(config.queue, (msg) => msg && handle(channel, publishChannel, msg), { noAck: false });
      state.brokerConnected = true;
      log.info({ queue: config.queue }, 'consumiendo');
      return;
    } catch (err) {
      log.warn({ err: err.message }, 'RabbitMQ no disponible, reintentando');
      await new Promise((r) => setTimeout(r, 2000));
    }
  }
}

function buildApp() {
  const app = Fastify({ logger: false });

  app.addHook('onRequest', async (req, reply) => {
    req.requestId = req.headers['x-request-id'] || randomUUID();
    const path = req.url.split('?')[0];
    if (!['/healthz', '/readyz', '/metrics'].includes(path)) {
      req.span = trace.getTracer('libre-closet-cna').startSpan(`${req.method} ${req.routeOptions.url || path}`,
        { kind: tracing.SpanKind.SERVER, attributes: { 'http.request.method': req.method, 'url.path': path, request_id: req.requestId } },
        tracing.extract(req.headers));
    }
    req.timer = httpDuration.startTimer({ route: req.routeOptions.url || req.url.split('?')[0] });
    reply.header('X-Request-ID', req.requestId);
  });
  app.addHook('onResponse', async (req, reply) => {
    const route = req.routeOptions.url || req.url.split('?')[0];
    req.timer();
    if (req.span) {
      req.span.setAttribute('http.response.status_code', reply.statusCode);
      if (reply.statusCode >= 500) req.span.setStatus({ code: tracing.SpanStatusCode.ERROR });
      req.span.end();
    }
    httpRequests.inc({ route, code: reply.statusCode });
    if (!['/healthz', '/readyz', '/metrics'].includes(route)) {
      log.info({ request_id: req.requestId, route, code: reply.statusCode }, `${req.method} ${req.url} ${reply.statusCode}`);
    }
  });

  app.get('/healthz', async () => ({ status: 'ok' }));

  app.get('/readyz', async (req, reply) => {
    let redisOk = false;
    try { redisOk = (await redis.ping()) === 'PONG'; } catch { redisOk = false; }
    const ready = redisOk && state.brokerConnected;
    reply.code(ready ? 200 : 503);
    return { status: ready ? 'ready' : 'not_ready', cache: redisOk, broker: state.brokerConnected };
  });

  app.get('/metrics', async (req, reply) => {
    reply.type(register.contentType);
    return register.metrics();
  });

  app.get('/v2/stats/outfits/top', async (req, reply) => {
    const limit = Number(req.query.limit || 5);
    if (!Number.isInteger(limit) || limit < 1 || limit > 50) {
      reply.code(400);
      return { error: 'bad_request', detail: 'limit tiene que estar entre 1 y 50' };
    }
    const raw = await redis.zrevrange('stats:top', 0, limit - 1, 'WITHSCORES');
    const top = [];
    for (let i = 0; i < raw.length; i += 2) {
      if (Number(raw[i + 1]) > 0) top.push({ outfit_id: Number(raw[i]), worn: Number(raw[i + 1]) });
    }
    return { count: top.length, outfits: top };
  });

  app.get('/v2/stats/outfits/:id', async (req, reply) => {
    const id = Number(req.params.id);
    if (!Number.isInteger(id)) {
      reply.code(400);
      return { error: 'bad_request', detail: 'id tiene que ser un número' };
    }
    const data = await redis.hgetall(`stats:outfit:${id}`);
    if (!data || Object.keys(data).length === 0) {
      reply.code(404);
      return { error: 'not_found', detail: 'ese outfit todavía no tiene usos registrados' };
    }
    return { outfit_id: id, worn: Number(data.worn || 0), last_worn_at: data.last_worn_at || null };
  });

  return app;
}

if (require.main === module) {
  const app = buildApp();
  app.listen({ port: config.port, host: '0.0.0.0' }).then(() => log.info({ port: config.port }, 'HTTP escuchando'));
  startConsumer();
}

module.exports = { buildApp };
