"""Consumidor durable de calendar.q con ack manual.

- Procesado bien o duplicado  -> ack
- Evento inválido             -> nack sin reencolar -> va a la DLQ
- Error transitorio (base)    -> nack con reencolado; tras 5 intentos RabbitMQ lo manda a la DLQ
"""
import asyncio
import json
import logging

import aio_pika
from prometheus_client import Counter

from . import db
from .handlers import InvalidEvent, plan
from .observability import request_id_var
from .tracing import SpanKind, Status, StatusCode, extract, tracer

log = logging.getLogger("consumer")

EVENTS = Counter("events_consumed_total", "Eventos consumidos por tipo y resultado", ["type", "result"])


class Consumer:
    def __init__(self, amqp_url: str, queue: str, pool, monolith):
        self.amqp_url = amqp_url
        self.queue_name = queue
        self.pool = pool
        self.monolith = monolith
        self.connection = None
        self.connected = False

    async def start(self) -> None:
        # connect_robust reconecta solo si se cae RabbitMQ
        while True:
            try:
                self.connection = await aio_pika.connect_robust(self.amqp_url)
                break
            except Exception as exc:  # noqa: BLE001
                log.warning("RabbitMQ no disponible (%s), reintentando", exc)
                await asyncio.sleep(2)
        self.connection.reconnect_callbacks.add(lambda *_: setattr(self, "connected", True))
        self.connection.close_callbacks.add(lambda *_: setattr(self, "connected", False))
        channel = await self.connection.channel()
        await channel.set_qos(prefetch_count=10)
        # passive=True: la cola la crea setup-topology; acá solo se usa
        queue = await channel.declare_queue(self.queue_name, passive=True)
        await queue.consume(self.handle)
        self.connected = True
        log.info("consumiendo de %s", self.queue_name)

    async def handle(self, message: aio_pika.abc.AbstractIncomingMessage) -> None:
        # El span continúa la traza que empezó el event-bridge (header traceparent del mensaje)
        kind = message.type or "desconocido"
        with tracer.start_as_current_span(
            f"consumir {kind}", context=extract(message.headers), kind=SpanKind.CONSUMER,
            attributes={"messaging.system": "rabbitmq", "messaging.destination.name": self.queue_name,
                        "messaging.message.id": str(message.message_id or "")},
        ) as span:
            await self._handle(message, kind, span)

    async def _handle(self, message, kind: str, span) -> None:
        request_id = (message.headers or {}).get("x-request-id") or "-"
        token = request_id_var.set(str(request_id))
        span.set_attribute("request_id", str(request_id))
        try:
            event = json.loads(message.body)
            operations = plan(event)
            for op, data in operations:
                if op == "upsert_entry":
                    exists = await self.monolith.outfit_exists(data["outfit_id"])
                    if exists is False:
                        raise InvalidEvent(f"el outfit {data['outfit_id']} no existe en el monolito")
            with tracer.start_as_current_span("postgres: aplicar evento", attributes={"db.system": "postgresql"}):
                applied = await db.apply(self.pool, event["event_id"], operations)
            await message.ack()
            result = "processed" if applied else "duplicate"
            span.set_attribute("resultado", result)
            EVENTS.labels(type=kind, result=result).inc()
            log.info("evento %s", result, extra={"extra_fields": {"type": kind, "event_id": event["event_id"]}})
        except (InvalidEvent, json.JSONDecodeError) as exc:
            await message.nack(requeue=False)
            span.set_status(Status(StatusCode.ERROR, "enviado a la DLQ"))
            EVENTS.labels(type=kind, result="dead_lettered").inc()
            log.error("evento inválido enviado a la DLQ: %s", exc, extra={"extra_fields": {"type": kind}})
        except Exception as exc:  # noqa: BLE001
            await message.nack(requeue=True)
            span.set_status(Status(StatusCode.ERROR, "se reintenta"))
            EVENTS.labels(type=kind, result="retry").inc()
            log.error("error transitorio, se reintenta: %s", exc, extra={"extra_fields": {"type": kind}})
        finally:
            request_id_var.reset(token)

    async def close(self) -> None:
        if self.connection:
            await self.connection.close()
