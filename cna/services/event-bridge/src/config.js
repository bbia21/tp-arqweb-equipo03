// Toda la configuración sale de variables de entorno (Twelve-Factor, factor III).
// Ningún secreto queda escrito en el código ni en la imagen.

function required(name) {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Falta la variable de entorno ${name}`);
  }
  return value;
}

function load() {
  return {
    pg: {
      host: process.env.PG_HOST || 'postgres',
      port: Number(process.env.PG_PORT || 5432),
      database: process.env.PG_DATABASE || 'closet',
      user: process.env.PG_USER || 'cna_cdc',
      password: required('PG_PASSWORD'),
    },
    publication: process.env.PG_PUBLICATION || 'cna_pub',
    slot: process.env.PG_SLOT || 'cna_slot',
    amqpUrl: required('AMQP_URL'),
    exchange: process.env.EXCHANGE || 'closet.events',
    httpPort: Number(process.env.HTTP_PORT || 8080),
  };
}

module.exports = { load };
