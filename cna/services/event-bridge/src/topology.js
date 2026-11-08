// Exchanges, colas y bindings de RabbitMQ. Se declaran una sola vez con setup-topology.js
// (usuario administrador). Es idempotente: se puede correr de nuevo sin romper nada.

const EXCHANGE = 'closet.events';
const DLX = 'closet.dlx';
const DLQ = 'closet.dlq';

// Colas durables (quorum) con reintentos limitados y cola de mensajes fallidos (ADR-010)
const QUORUM_ARGS = {
  'x-queue-type': 'quorum',
  'x-delivery-limit': 5,
  'x-dead-letter-exchange': DLX,
};

const QUEUES = [
  { name: 'calendar.q', bindings: ['closet.calendar.*', 'closet.outfit.*'] },
  { name: 'stats.q', bindings: ['closet.calendar.updated'] },
];

async function declare(channel) {
  await channel.assertExchange(EXCHANGE, 'topic', { durable: true });
  await channel.assertExchange(DLX, 'fanout', { durable: true });

  await channel.assertQueue(DLQ, { durable: true });
  await channel.bindQueue(DLQ, DLX, '');

  for (const queue of QUEUES) {
    await channel.assertQueue(queue.name, { durable: true, arguments: QUORUM_ARGS });
    for (const key of queue.bindings) {
      await channel.bindQueue(queue.name, EXCHANGE, key);
    }
  }

  // Cola solo para inspeccionar a mano desde la consola (evidencia F6-E12).
  // Guarda como máximo 1000 mensajes y no la consume ningún servicio.
  await channel.assertQueue('debug.q', { durable: true, arguments: { 'x-max-length': 1000 } });
  await channel.bindQueue('debug.q', EXCHANGE, 'closet.#');
}

module.exports = { declare, EXCHANGE, DLX, DLQ, QUEUES, QUORUM_ARGS };
