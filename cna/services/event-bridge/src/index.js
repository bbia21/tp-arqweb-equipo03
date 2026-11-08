// event-bridge: lee el WAL de PostgreSQL por replicación lógica (CDC) y publica
// cada cambio de outfit / outfit_calendar como evento en RabbitMQ.
// No toca el código de Libre Closet: solo lee lo que la base ya registra.
const http = require('node:http');
const { Client } = require('pg');
const { LogicalReplicationService, PgoutputPlugin } = require('pg-logical-replication');

const config = require('./config').load();
const logger = require('./logger');
const broker = require('./broker');
const { toEvent } = require('./envelope');
const metrics = require('./metrics');

const state = { replicating: false, brokerConnected: false };

async function ensureSlot() {
  const client = new Client(config.pg);
  await client.connect();
  try {
    const { rows } = await client.query(
      'SELECT 1 FROM pg_replication_slots WHERE slot_name = $1',
      [config.slot],
    );
    if (rows.length === 0) {
      await client.query("SELECT pg_create_logical_replication_slot($1, 'pgoutput')", [config.slot]);
      logger.info({ slot: config.slot }, 'Slot de replicación creado');
    }
  } finally {
    await client.end();
  }
}

function startHttpServer() {
  const server = http.createServer(async (req, res) => {
    const route = req.url.split('?')[0];
    const end = metrics.httpDuration.startTimer({ route });
    let code = 200;
    let body = '';
    let type = 'application/json';

    if (route === '/healthz') {
      body = JSON.stringify({ status: 'ok' });
    } else if (route === '/readyz') {
      const ready = state.replicating && state.brokerConnected;
      code = ready ? 200 : 503;
      body = JSON.stringify({ status: ready ? 'ready' : 'not_ready', ...state });
    } else if (route === '/metrics') {
      type = metrics.register.contentType;
      body = await metrics.register.metrics();
    } else {
      code = 404;
      body = JSON.stringify({ error: 'not_found' });
    }

    res.writeHead(code, { 'Content-Type': type });
    res.end(body);
    metrics.httpRequests.inc({ route, code });
    end();
  });
  server.listen(config.httpPort, () => logger.info({ port: config.httpPort }, 'HTTP escuchando'));
}

async function main() {
  startHttpServer();

  const { channel } = await broker.connect(config.amqpUrl);
  state.brokerConnected = true;

  await ensureSlot();

  const service = new LogicalReplicationService(config.pg, {
    // Confirmamos a mano, y solo después de que RabbitMQ guardó los eventos
    acknowledge: { auto: false, timeoutSeconds: 10 },
    // Procesa un mensaje a la vez, en orden
    flowControl: { enabled: true },
  });
  const plugin = new PgoutputPlugin({ protoVersion: 1, publicationNames: [config.publication] });

  let pending = [];

  service.on('start', () => {
    state.replicating = true;
    logger.info({ slot: config.slot, publication: config.publication }, 'Replicación iniciada');
  });

  service.on('data', async (lsn, message) => {
    if (message.tag === 'begin') {
      pending = [];
      return;
    }
    if (message.tag === 'insert' || message.tag === 'update' || message.tag === 'delete') {
      const event = toEvent(message);
      if (event) pending.push(event);
      return;
    }
    if (message.tag === 'commit') {
      try {
        for (const event of pending) {
          await broker.publish(channel, config.exchange, event);
          metrics.eventsPublished.inc({ type: event.type });
          metrics.lastEventTimestamp.setToCurrentTime();
          logger.info(
            { request_id: event.request_id, event_id: event.event_id, type: event.type },
            'Evento publicado',
          );
        }
        pending = [];
        await service.acknowledge(message.commitEndLsn || lsn);
      } catch (err) {
        // Sin acknowledge: PostgreSQL reenvía esta transacción al reconectar
        logger.error({ err: err.message }, 'No se pudo publicar; reiniciando sin confirmar');
        process.exit(1);
      }
    }
  });

  service.on('error', (err) => {
    state.replicating = false;
    logger.error({ err: err.message }, 'Error en la replicación');
  });

  // Si la conexión de replicación se corta, se vuelve a suscribir sola
  (function subscribe() {
    service
      .subscribe(plugin, config.slot)
      .catch((err) => {
        state.replicating = false;
        logger.error({ err: err.message }, 'Suscripción cortada');
      })
      .then(() => setTimeout(subscribe, 2000));
  })();
}

main().catch((err) => {
  logger.error({ err: err.message }, 'Error fatal');
  process.exit(1);
});
