# Libre Closet Cloud Native — carpeta `cna/`

TP Integrador II de Arquitectura Web (FP-UNA 2026). Monolito: Libre Closet 0.6.0 sobre PostgreSQL.
Integración por CDC: `event-bridge` lee el WAL de PostgreSQL (replicación lógica) y publica eventos en RabbitMQ.

## Estructura

```
cna/
├── services/
│   ├── event-bridge/      Node 22: replicación lógica -> RabbitMQ
│   ├── calendar-svc/      S1 · Python/FastAPI + PostgreSQL propio
│   ├── wear-stats-svc/    S2 · Node/Fastify + Redis propio
│   └── weather-svc/       S3 · Python/FastAPI + Redis como caché
├── deploy/
│   ├── vm1/               compose del event-bridge (corre al lado de PostgreSQL)
│   ├── vm2/               compose de RabbitMQ + S1, S2, S3 y sus almacenes
│   └── rabbitmq/          compose de RabbitMQ (prueba en VM-1) + usuarios por servicio
├── Makefile               make test: pruebas de todos los servicios
└── README.md
```

## Servicios y endpoints

Todos exponen además `GET /healthz`, `GET /readyz` y `GET /metrics`, logs JSON y `X-Request-ID`.

| Servicio | Puerto en VM-2 | Endpoints | Datos |
| --- | --- | --- | --- |
| S1 calendar-svc | 8001 | `GET /v2/calendar?owner_id=&from=&to=` · `GET /v2/calendar/today?owner_id=` | PostgreSQL propio; consume `calendar.q` |
| S2 wear-stats-svc | 8002 | `GET /v2/stats/outfits/top?limit=` · `GET /v2/stats/outfits/{id}` | Redis (AOF); consume `stats.q`, publica `stats.outfit.worn` |
| S3 weather-svc | 8003 | `GET /v2/weather?lat=&lon=&days=&unit=` | Redis como caché; llama a Open-Meteo con timeout, reintentos y circuito |

Comportamiento ante fallas de los consumidores (S1, S2):
- evento procesado o repetido (mismo `event_id`) → `ack`
- evento inválido → `nack` sin reencolar → `closet.dlq`
- error transitorio → `nack` con reencolado; a los 5 intentos RabbitMQ lo manda a `closet.dlq`

## Paso a paso de esta noche (todo en VM-1)

Requisito previo: en PostgreSQL ya existen el rol `cna_cdc`, la publicación `cna_pub` y `wal_level=logical`.

### 1. RabbitMQ

```bash
cd ~/cna/deploy/rabbitmq
cp .env.example .env
sed -i "s/^RABBIT_ADMIN_PASSWORD=.*/RABBIT_ADMIN_PASSWORD=$(openssl rand -hex 12)/" .env
sed -i "s/^RABBIT_BRIDGE_PASSWORD=.*/RABBIT_BRIDGE_PASSWORD=$(openssl rand -hex 12)/" .env
docker compose up -d
docker compose ps        # esperar a que diga (healthy)
```

### 2. Configuración del event-bridge

```bash
cd ~/cna/deploy/vm1
{
  grep '^CDC_PASSWORD=' /srv/libre-closet/.env
  echo "RABBIT_USER=admin"
  grep '^RABBIT_ADMIN_PASSWORD=' ../rabbitmq/.env | sed 's/^RABBIT_ADMIN_PASSWORD=/RABBIT_PASSWORD=/'
  echo "RABBIT_HOST=host.docker.internal"
} > .env
chmod 600 .env
cat .env                 # tienen que aparecer las 4 variables con valor
```

### 3. Construir la imagen y crear la topología (exchanges, colas, DLQ)

```bash
docker compose build
docker compose run --rm event-bridge node src/setup-topology.js
```

### 4. Levantar el bridge y hacer la carga inicial

```bash
docker compose up -d
docker compose logs -f event-bridge      # Ctrl+C para salir
docker compose run --rm event-bridge node src/backfill.js
```

### 5. Probar: un cambio en el calendario llega a RabbitMQ

1. Agendar un outfit o marcarlo como usado en https://librecloset.arqweb.test
2. En los logs del bridge aparece `Evento publicado` con `type: closet.calendar.created` o `updated`.
3. En la consola de RabbitMQ (http://127.0.0.1:15672, usuario `admin`) → Queues → `debug.q` → Get messages.
   Captura = evidencia F6-E12.

### Pruebas automatizadas

```bash
cd ~/cna/services/event-bridge && npm test     # requiere Node 22 instalado en la VM
# o sin instalar Node:
docker run --rm -v "$PWD":/app -w /app node:22-alpine sh -c "npm ci && npm test"
```

## Variables de entorno del event-bridge

| Variable | Ejemplo | Para qué |
| --- | --- | --- |
| `PG_HOST` / `PG_PORT` / `PG_DATABASE` | postgres / 5432 / closet | Conexión a la base de Libre Closet |
| `PG_USER` / `PG_PASSWORD` | cna_cdc / (secreto) | Usuario con permiso REPLICATION y SELECT solo en outfit y outfit_calendar |
| `PG_PUBLICATION` / `PG_SLOT` | cna_pub / cna_slot | Qué tablas se leen y desde dónde se retoma |
| `AMQP_URL` | amqp://bridge:...@VM2:5672 | Conexión a RabbitMQ |
| `EXCHANGE` | closet.events | Exchange donde se publican los eventos |

## Cómo garantiza cero pérdida de eventos (CA-6)

1. PostgreSQL guarda en el slot `cna_slot` hasta dónde leyó el bridge.
2. El bridge publica cada evento con *publisher confirms* y espera la confirmación de RabbitMQ.
3. Recién entonces le confirma a PostgreSQL la posición (`acknowledge`).
4. Si el bridge o RabbitMQ se caen antes del paso 3, PostgreSQL vuelve a enviar esos cambios al reconectar.
   Por eso los consumidores deben ser idempotentes por `event_id` (ADR-010).
