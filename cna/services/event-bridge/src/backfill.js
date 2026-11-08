// Carga inicial: publica todos los outfits y entradas del calendario que ya existen
// como eventos *.created, para que S1 arranque con todos los datos.
// Uso: docker compose run --rm event-bridge node src/backfill.js
const { Client } = require('pg');
const config = require('./config').load();
const logger = require('./logger');
const broker = require('./broker');
const { toEvent } = require('./envelope');

async function main() {
  const { connection, channel } = await broker.connect(config.amqpUrl);
  const client = new Client(config.pg);
  await client.connect();

  let total = 0;
  // Primero outfits, después calendario (el calendario hace referencia a outfits)
  for (const table of ['outfit', 'outfit_calendar']) {
    const { rows } = await client.query(`SELECT * FROM ${table} ORDER BY id`);
    for (const row of rows) {
      const event = toEvent({ tag: 'insert', relation: { name: table }, new: row });
      await broker.publish(channel, config.exchange, event);
      total += 1;
    }
    logger.info({ table, rows: rows.length }, 'Tabla publicada');
  }

  await client.end();
  connection.removeAllListeners('close');
  await connection.close();
  logger.info({ total }, 'Carga inicial terminada');
}

main().catch((err) => {
  logger.error({ err: err.message }, 'Falló la carga inicial');
  process.exit(1);
});
