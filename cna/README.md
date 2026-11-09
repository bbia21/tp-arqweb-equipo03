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
│   ├── vm1/               compose del event-bridge + configuración del gateway Nginx
│   ├── vm2/               compose de RabbitMQ + S1, S2, S3 y sus almacenes
│   └── rabbitmq/          compose de RabbitMQ (prueba en VM-1) + usuarios por servicio
├── deploy/up.sh, down.sh  despliegue y baja en un comando
├── Makefile               make up / down / status / test
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

## Despliegue en un comando (CA-7)

Requisitos previos de infraestructura (una sola vez):

1. VM-1 (`librecloset`, 192.168.56.10): monolito del TP I corriendo en `/srv/libre-closet`
   (Libre Closet 0.6.0 + PostgreSQL con `wal_level=logical`) y Nginx con el certificado del sitio.
2. VM-2 (`cna-node1`, 192.168.56.11): Docker instalado y UFW + `DOCKER-USER` configurados.
3. SSH sin contraseña de VM-1 a VM-2: `ssh-copy-id admins@192.168.56.11`.

Despliegue, desde VM-1 en la carpeta `cna/`:

```bash
make up        # CDC + RabbitMQ + S1, S2, S3 + event-bridge + gateway, y prueba de humo
make status    # contenedores de los dos nodos
make down      # baja la parte cloud native (BORRAR_DATOS=1 make down borra también los volúmenes)
```

`make up` genera las contraseñas que falten en `deploy/vm1/.env` y `deploy/vm2/.env` (no se versionan;
ver los `.env.example`), etiqueta las imágenes como `1.0.0-<hash del commit>` y despliega VM-2 por SSH
con un contexto de Docker (`cna-node1`).

### Carga inicial del índice de S1 (solo la primera vez)

```bash
docker compose -p vm1 -f deploy/vm1/docker-compose.yml --env-file deploy/vm1/.env run --rm event-bridge node src/backfill.js
```

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

## Observabilidad, caos y carga (Fase 7)

`make up` también levanta, en VM-2, Prometheus (métricas y alertas), Loki + Promtail (logs de los
dos nodos y del gateway), Jaeger (trazas distribuidas con OpenTelemetry) y Grafana con el tablero RED
ya cargado. Se accede por túnel SSH:

```powershell
ssh -p 2223 -L 3000:localhost:3000 -L 9090:localhost:9090 -L 16686:localhost:16686 admins@127.0.0.1
```

- `observability/` — configuración de Prometheus, alertas, Loki/Promtail y Grafana (se copian dentro de las imágenes).
- `perf/load.js` — prueba de carga k6 (monolito vs S1, escalado de S3); `perf/sondeo.sh` mide el MTTR.
- `docs/fase7-guion.md` — guion paso a paso de los experimentos X1–X5, k6, Trivy/SBOM y rotación de credenciales.
