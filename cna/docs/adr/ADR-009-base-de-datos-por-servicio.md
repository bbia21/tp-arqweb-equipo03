# ADR-009: Base de datos por servicio

**Estatus:** Aceptado

## Contexto

Los microservicios necesitan persistencia propia sin acoplarse al esquema de Libre Closet. Las tablas
`user`, `outfit` y `garment` son compartidas por varios módulos del monolito (ver matriz de acoplamiento, A1).

## Decisión

Cada servicio tiene su almacén, elegido según lo que guarda, y **ningún microservicio se conecta al
PostgreSQL del monolito**:

| Servicio | Almacén | Qué guarda | Por qué |
| --- | --- | --- | --- |
| S1 calendar-svc | PostgreSQL 16 propio (`calendar-db`) | Copia del calendario y nombres de outfits; `processed_event` | Consultas por rango de fechas e idempotencia transaccional |
| S2 wear-stats-svc | Redis 7 con AOF (`stats-db`) | Contadores por outfit, ranking, `processed:<event_id>` | Suma atómica (script Lua) y ranking con *sorted sets* |
| S3 weather-svc | Redis 7 sin persistencia (`weather-cache`) | Pronósticos con TTL de 30 min y copia vieja de 24 h | Es una caché: se puede perder sin daño |

Solo el `event-bridge` lee la base del monolito, por replicación, con un rol limitado (ADR-006).

## Alternativas descartadas

| Alternativa | Por qué se descartó |
| --- | --- |
| Base compartida con un esquema por servicio | Acopla el despliegue y las migraciones; un error de un servicio afecta al monolito |
| Que S1 consulte directo las tablas de Libre Closet | Es exactamente el acoplamiento que el patrón busca eliminar |
| PostgreSQL o MongoDB para S2 (sugerido en la consigna para auditoría) | S2 solo guarda contadores: Redis resuelve la suma atómica e idempotente con menos RAM |

## Consecuencias

**Positivas**
- Cada servicio se despliega, escala y falla por separado; se verifica con `pg_stat_activity` (B4).

**Negativas**
- Datos duplicados: el calendario existe en el monolito y en S1.
- Más contenedores y más RAM (cuatro almacenes en lugar de uno).
- Consistencia eventual entre almacenes (ADR-010).
