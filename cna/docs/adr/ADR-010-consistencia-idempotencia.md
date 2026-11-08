# ADR-010: Consistencia eventual, idempotencia y mensajes fallidos

**Estatus:** Aceptado

## Contexto

S1 y S2 se actualizan de forma asíncrona. RabbitMQ y el slot de PostgreSQL garantizan entrega
*al menos una vez*: ante una caída, un mismo evento puede llegar dos veces.

## Decisión

1. **Consistencia eventual**, con un objetivo medible: un cambio en el monolito se ve en `/v2/*` en menos de 5 s (CA-3).
2. **Idempotencia por `event_id`** (UUID generado por el bridge):
   - S1 inserta el `event_id` en `processed_event` dentro de la misma transacción que aplica el cambio.
   - S2 usa un script Lua atómico: `SET processed:<event_id> NX` y, solo si no existía, suma el contador.
   - Si el `event_id` ya estaba, se confirma el mensaje sin aplicar nada (evidencia F6-E5).
3. **Mensajes fallidos:**
   - Evento inválido (JSON roto, sin sobre, outfit inexistente en el monolito) → `nack` sin reencolar → `closet.dlq`.
   - Error transitorio (base caída) → `nack` con reencolado; a los **5 intentos** RabbitMQ lo manda a `closet.dlq`.
4. Orden: el bridge publica en el orden de las transacciones; cada consumidor procesa con `prefetch` 10.

## Alternativas descartadas

| Alternativa | Por qué se descartó |
| --- | --- |
| Transacciones distribuidas (2PC) | No soportado entre PostgreSQL, Redis y RabbitMQ; bloquearía al monolito |
| Entrega "exactamente una vez" en el broker | No existe de punta a punta; se logra el mismo efecto con idempotencia en el consumidor |
| Reintentar indefinidamente | Un mensaje roto trabaría la cola para siempre |

## Consecuencias

**Positivas**
- Reintentar es siempre seguro; reiniciar un consumidor no pierde ni duplica (CA-6, experimento X2 y X3).

**Negativas**
- Durante unos segundos, `/v2/calendar` puede mostrar datos viejos.
- Hay que revisar la DLQ a mano (se dispara una alerta si tiene mensajes, C3).
- Con `prefetch` > 1, dos eventos del mismo registro podrían aplicarse fuera de orden si uno se reintenta.
