// Crea exchanges, colas y bindings en RabbitMQ. Se corre una vez con el usuario admin:
// docker compose run --rm -e AMQP_URL=amqp://admin:CLAVE@HOST:5672 event-bridge node src/setup-topology.js
const amqp = require('amqplib');
const logger = require('./logger');
const topology = require('./topology');

async function main() {
  const url = process.env.AMQP_URL;
  if (!url) throw new Error('Falta AMQP_URL');
  const connection = await amqp.connect(url);
  const channel = await connection.createChannel();
  await topology.declare(channel);
  await connection.close();
  logger.info(
    { exchange: topology.EXCHANGE, queues: topology.QUEUES.map((q) => q.name), dlq: topology.DLQ },
    'Topología creada',
  );
}

main().catch((err) => {
  logger.error({ err: err.message }, 'No se pudo crear la topología');
  process.exit(1);
});
