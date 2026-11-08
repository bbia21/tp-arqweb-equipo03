// Pruebas de la lógica de S2. Correr con: npm test
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { wornDelta, InvalidEvent, keysFor } = require('../src/logic');

const ev = (type, payload) => ({ event_id: 'e1', type, version: '1', payload });

test('marcar como usado suma 1', () => {
  const r = wornDelta(ev('closet.calendar.updated', { outfit_id: 5, worn_at: '2026-11-07T21:25:28Z', previous: { worn_at: null } }));
  assert.equal(r.delta, 1);
  assert.equal(r.outfitId, 5);
});

test('desmarcar resta 1', () => {
  const r = wornDelta(ev('closet.calendar.updated', { outfit_id: 5, worn_at: null, previous: { worn_at: '2026-11-07T21:25:28Z' } }));
  assert.equal(r.delta, -1);
});

test('cambiar solo las notas no cambia el contador', () => {
  const r = wornDelta(ev('closet.calendar.updated', { outfit_id: 5, worn_at: null, notes: 'x', previous: { worn_at: null } }));
  assert.equal(r.delta, 0);
});

test('borrar una entrada ya usada resta 1', () => {
  assert.equal(wornDelta(ev('closet.calendar.deleted', { outfit_id: 5, worn_at: '2026-11-07T21:25:28Z' })).delta, -1);
});

test('un mensaje sin sobre de evento es inválido (va a la DLQ)', () => {
  assert.throws(() => wornDelta({ hola: 'mundo' }), InvalidEvent);
});

test('las claves de idempotencia dependen del event_id', () => {
  assert.deepEqual(keysFor('abc', 5), ['processed:abc', 'stats:outfit:5', 'stats:top']);
});
