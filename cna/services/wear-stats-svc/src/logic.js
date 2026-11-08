// Lógica pura de S2 (sin Redis ni RabbitMQ) para poder probarla.

class InvalidEvent extends Error {}

/**
 * Cuánto cambia el contador de "veces usado" por este evento:
 *  +1 si el outfit pasó a usado, -1 si se desmarcó o se borró una entrada usada, 0 si no cambia.
 */
function wornDelta(event) {
  if (!event || typeof event !== 'object' || !event.event_id || !event.type) {
    throw new InvalidEvent('el mensaje no tiene el sobre de evento (type, event_id)');
  }
  const p = event.payload;
  if (!p || typeof p !== 'object') {
    throw new InvalidEvent('payload vacío o inválido');
  }

  let delta = 0;
  if (event.type === 'closet.calendar.updated') {
    const before = p.previous ? p.previous.worn_at : null;
    const after = p.worn_at;
    if (!before && after) delta = 1;
    if (before && !after) delta = -1;
  } else if (event.type === 'closet.calendar.created') {
    delta = p.worn_at ? 1 : 0;
  } else if (event.type === 'closet.calendar.deleted') {
    delta = p.worn_at ? -1 : 0;
  }

  if (delta !== 0 && (p.outfit_id === undefined || p.outfit_id === null)) {
    throw new InvalidEvent('falta outfit_id');
  }
  return { delta, outfitId: p.outfit_id, wornAt: p.worn_at || (p.previous && p.previous.worn_at) || null };
}

// Script Lua: marcar el event_id como procesado y sumar el contador en UNA operación atómica.
// Si el event_id ya existía, no suma nada (idempotencia, ADR-010).
const APPLY_SCRIPT = `
if redis.call('SET', KEYS[1], '1', 'NX', 'EX', ARGV[1]) then
  local delta = tonumber(ARGV[2])
  if delta ~= 0 then
    redis.call('HINCRBY', KEYS[2], 'worn', delta)
    redis.call('ZINCRBY', KEYS[3], delta, ARGV[3])
    if delta > 0 then
      redis.call('HSET', KEYS[2], 'last_worn_at', ARGV[4])
    end
  end
  return 1
end
return 0
`;

const PROCESSED_TTL_SECONDS = 7 * 24 * 60 * 60;

function keysFor(eventId, outfitId) {
  return [`processed:${eventId}`, `stats:outfit:${outfitId}`, 'stats:top'];
}

module.exports = { wornDelta, InvalidEvent, APPLY_SCRIPT, PROCESSED_TTL_SECONDS, keysFor };
