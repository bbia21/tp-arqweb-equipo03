// Traduce un cambio de PostgreSQL (mensaje pgoutput) al sobre de evento común del TP (A3).
// Este archivo es la "capa anticorrupción": el resto del sistema nunca ve nombres de tablas.
const { randomUUID } = require('node:crypto');

// Tabla de Libre Closet -> nombre de entidad en los eventos
const ENTITIES = {
  outfit_calendar: 'calendar',
  outfit: 'outfit',
};

// Operación de PostgreSQL -> verbo del evento
const OPERATIONS = {
  insert: 'created',
  update: 'updated',
  delete: 'deleted',
};

const EVENT_VERSION = '1';

/**
 * @param {{tag: string, relation: {name: string}, new?: object, old?: object, key?: object}} change
 * @param {{now?: () => Date, uuid?: () => string}} [deps] para poder probarlo con valores fijos
 * @returns {object|null} el evento, o null si la tabla u operación no interesa
 */
function toEvent(change, deps = {}) {
  const now = deps.now || (() => new Date());
  const uuid = deps.uuid || randomUUID;

  const entity = ENTITIES[change.relation && change.relation.name];
  const verb = OPERATIONS[change.tag];
  if (!entity || !verb) {
    return null;
  }

  let payload;
  if (change.tag === 'insert') {
    payload = { ...change.new };
  } else if (change.tag === 'update') {
    // "previous" permite saber qué cambió (por ejemplo, worn_at de null a una fecha)
    payload = { ...change.new, previous: change.old || null };
  } else {
    payload = { ...(change.old || change.key || {}) };
  }

  return {
    event_id: uuid(),
    type: `closet.${entity}.${verb}`,
    version: EVENT_VERSION,
    occurred_at: now().toISOString(),
    // El WAL no trae el X-Request-ID de la petición original: se genera uno nuevo
    // (limitación documentada en ADR-006).
    request_id: uuid(),
    payload,
  };
}

module.exports = { toEvent, ENTITIES, OPERATIONS };
