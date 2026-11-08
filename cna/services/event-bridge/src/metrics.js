const client = require('prom-client');

const register = new client.Registry();
client.collectDefaultMetrics({ register });

const httpRequests = new client.Counter({
  name: 'http_requests_total',
  help: 'Peticiones HTTP por ruta y código',
  labelNames: ['route', 'code'],
  registers: [register],
});

const httpDuration = new client.Histogram({
  name: 'http_request_duration_seconds',
  help: 'Latencia de las peticiones HTTP',
  labelNames: ['route'],
  buckets: [0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5],
  registers: [register],
});

const eventsPublished = new client.Counter({
  name: 'bridge_events_published_total',
  help: 'Eventos publicados en RabbitMQ por tipo',
  labelNames: ['type'],
  registers: [register],
});

const lastEventTimestamp = new client.Gauge({
  name: 'bridge_last_event_timestamp_seconds',
  help: 'Momento del último evento publicado',
  registers: [register],
});

module.exports = { register, httpRequests, httpDuration, eventsPublished, lastEventTimestamp };
