// Conexión a RabbitMQ con "publisher confirms": recién cuando el broker confirma
// que guardó el mensaje, el bridge le avisa a PostgreSQL que puede avanzar (cero pérdida).
const amqp = require('amqplib');
const logger = require('./logger');
const tracing = require('./tracing');

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function connect(url, { retries = 30, delayMs = 2000 } = {}) {
  for (let attempt = 1; attempt <= retries; attempt += 1) {
    try {
      const connection = await amqp.connect(url);
      const channel = await connection.createConfirmChannel();
      // Si se cae la conexión, el proceso termina y Docker lo reinicia.
      // Lo no confirmado se vuelve a leer del slot de replicación: no se pierde nada.
      connection.on('close', () => {
        logger.error('Se cerró la conexión con RabbitMQ; reiniciando');
        process.exit(1);
      });
      connection.on('error', (err) => logger.error({ err: err.message }, 'Error en RabbitMQ'));
      logger.info('Conectado a RabbitMQ');
      return { connection, channel };
    } catch (err) {
      logger.warn({ attempt, err: err.message }, 'RabbitMQ no disponible, reintentando');
      await sleep(delayMs);
    }
  }
  throw new Error('No se pudo conectar a RabbitMQ');
}

async function publish(channel, exchange, event) {
  channel.publish(exchange, event.type, Buffer.from(JSON.stringify(event)), {
    persistent: true,
    contentType: 'application/json',
    messageId: event.event_id,
    type: event.type,
    timestamp: Math.floor(Date.now() / 1000),
    headers: tracing.inject({ 'x-request-id': event.request_id }), // + traceparent
  });
  await channel.waitForConfirms();
}

module.exports = { connect, publish };
