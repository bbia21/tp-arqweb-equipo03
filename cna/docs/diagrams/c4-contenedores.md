# C4 nivel 2 · Contenedores (F5-E6)

```mermaid
C4Container
  title Libre Closet Cloud Native · contenedores, nodos, puertos y protocolos

  Person(usuario, "Usuaria / cliente de la API")
  System_Ext(openmeteo, "Open-Meteo", "API del clima")

  Deployment_Node(vm1, "VM-1 · librecloset · 192.168.56.10", "Ubuntu 24.04, 2 vCPU, 4 GB") {
    Container(nginx, "Nginx 1.24", "Gateway", "TLS 1.3, HSTS, X-Request-ID, rate limit 20 r/s, 503 JSON · :80 → :443")
    Container(monolito, "Libre Closet 0.6.0", "NestJS + Handlebars", "Prendas, outfits, calendario, usuarios · 127.0.0.1:3000")
    ContainerDb(pg, "PostgreSQL 16", "wal_level=logical", "Base del monolito · 127.0.0.1:5432")
    Container(bridge, "event-bridge", "Node 22", "Lee el WAL (pgoutput) y publica eventos · :8080 /metrics")
  }

  Deployment_Node(vm2, "VM-2 · cna-node1 · 192.168.56.11", "Ubuntu 24.04, 2 vCPU, 4 GB") {
    Container(rabbit, "RabbitMQ 4.1", "AMQP 0-9-1", "closet.events, calendar.q, stats.q, closet.dlq · :5672")
    Container(s1, "S1 calendar-svc", "Python / FastAPI", "GET /v2/calendar · :8001")
    ContainerDb(s1db, "calendar-db", "PostgreSQL 16", "Copia del calendario + processed_event")
    Container(s2, "S2 wear-stats-svc", "Node / Fastify", "GET /v2/stats · :8002")
    ContainerDb(s2db, "stats-db", "Redis 7 (AOF)", "Contadores y ranking")
    Container(s3, "S3 weather-svc", "Python / FastAPI", "GET /v2/weather · :8003")
    ContainerDb(s3db, "weather-cache", "Redis 7", "Caché de pronósticos (TTL 30 min)")
  }

  Rel(usuario, nginx, "HTTPS", "443")
  Rel(nginx, monolito, "HTTP", "127.0.0.1:3000")
  Rel(nginx, s1, "HTTP /v2/calendar", "intnet :8001")
  Rel(nginx, s2, "HTTP /v2/stats", "intnet :8002")
  Rel(nginx, s3, "HTTP /v2/weather", "intnet :8003")
  Rel(monolito, pg, "SQL", "5432")
  Rel(bridge, pg, "Replicación lógica", "5432 · rol cna_cdc")
  Rel(bridge, rabbit, "Publica eventos", "AMQP :5672 · usuario bridge")
  Rel(rabbit, s1, "calendar.q", "AMQP")
  Rel(rabbit, s2, "stats.q", "AMQP")
  Rel(s1, monolito, "Verifica outfit (svc-cna)", "HTTPS 443")
  Rel(s1, s1db, "SQL")
  Rel(s2, s2db, "RESP")
  Rel(s3, s3db, "RESP")
  Rel(s3, openmeteo, "HTTPS", "timeout 2 s, 3 reintentos, circuito")
```

Ningún contenedor de VM-2 se conecta a PostgreSQL del monolito; solo el event-bridge, dentro de VM-1
(ADR-006, ADR-009). En VM-2, UFW y la cadena `DOCKER-USER` solo aceptan conexiones desde 192.168.56.10.
