# ADR-007: Selección del broker de mensajes

**Estatus:** Aceptado

## Contexto

Se necesita entrega confiable de eventos entre el `event-bridge` y los consumidores (S1, S2), con colas
durables, confirmación manual y una cola de mensajes fallidos (DLQ). Las VMs tienen 4 GB de RAM.

## Decisión

**RabbitMQ 4.1** (imagen `management-alpine` con el plugin `rabbitmq_prometheus`):

- Exchange `closet.events` de tipo *topic*; las claves de ruteo son el tipo de evento (`closet.calendar.updated`).
- Colas **quorum** `calendar.q` y `stats.q`, durables, con `x-delivery-limit: 5` y
  `x-dead-letter-exchange: closet.dlx` → cola `closet.dlq`.
- *Publisher confirms* en el bridge y `ack` manual en los consumidores.
- Un usuario por componente con permisos mínimos (`bridge` solo publica; `calendar` y `stats` solo leen su cola).

## Alternativas descartadas

| Alternativa | Ventaja | Por qué se descartó |
| --- | --- | --- |
| NATS JetStream | ~30 MB de RAM, muy simple | No tiene DLQ nativa: hay que programar el reenvío con *advisories* |
| Redis Streams | Ya se usa Redis en S2 y S3 | Sin DLQ ni límite de reintentos nativos; mezclar caché y broker en el mismo almacén |
| Kafka | Retención y reproceso | Demasiado pesado para VMs de 4 GB; no aporta nada que el TP necesite |

## Consecuencias

**Positivas**
- DLQ y límite de reintentos nativos (evidencia F6-E13).
- Consola web y API HTTP para inspeccionar mensajes (F6-E12) y métricas Prometheus (profundidad de colas, C3).

**Negativas**
- Consume ~150–200 MB de RAM frente a ~30 MB de NATS (límite de 512 MB declarado).
- Es un punto único de falla en VM-2: si cae, los eventos se acumulan en el slot de PostgreSQL hasta que vuelve
  (no se pierden, pero S1 y S2 quedan desactualizados).
