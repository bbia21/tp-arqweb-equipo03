// Pruebas del sobre de evento (contrato A3). Correr con: npm test
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { toEvent } = require('../src/envelope');

const fixed = {
  now: () => new Date('2026-11-20T14:03:11.000Z'),
  uuid: () => '00000000-0000-4000-8000-000000000000',
};

test('un INSERT en outfit_calendar produce closet.calendar.created con el sobre completo', () => {
  const event = toEvent(
    {
      tag: 'insert',
      relation: { name: 'outfit_calendar' },
      new: { id: 17, outfit_id: 5, owner_id: 3, worn_at: null },
    },
    fixed,
  );
  assert.equal(event.type, 'closet.calendar.created');
  assert.equal(event.version, '1');
  assert.equal(event.occurred_at, '2026-11-20T14:03:11.000Z');
  assert.ok(event.event_id);
  assert.ok(event.request_id);
  assert.deepEqual(event.payload, { id: 17, outfit_id: 5, owner_id: 3, worn_at: null });
});

test('un UPDATE incluye la fila anterior en payload.previous', () => {
  const event = toEvent(
    {
      tag: 'update',
      relation: { name: 'outfit_calendar' },
      old: { id: 17, worn_at: null },
      new: { id: 17, worn_at: '2026-11-21T09:10:00.000Z' },
    },
    fixed,
  );
  assert.equal(event.type, 'closet.calendar.updated');
  assert.equal(event.payload.worn_at, '2026-11-21T09:10:00.000Z');
  assert.deepEqual(event.payload.previous, { id: 17, worn_at: null });
});

test('un DELETE en outfit usa la fila anterior como payload', () => {
  const event = toEvent(
    { tag: 'delete', relation: { name: 'outfit' }, old: { id: 5, name: 'Oficina' }, key: null },
    fixed,
  );
  assert.equal(event.type, 'closet.outfit.deleted');
  assert.deepEqual(event.payload, { id: 5, name: 'Oficina' });
});

test('las tablas que no están publicadas se ignoran', () => {
  assert.equal(toEvent({ tag: 'insert', relation: { name: 'user' }, new: { id: 1 } }, fixed), null);
});
