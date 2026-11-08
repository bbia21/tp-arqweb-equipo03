# Diagramas de secuencia (F5-E7)

## 1. Marcar un outfit como usado → calendario y estadísticas actualizados (asíncrono)

```mermaid
sequenceDiagram
  autonumber
  actor U as Usuaria
  participant N as Nginx (VM-1)
  participant L as Libre Closet
  participant P as PostgreSQL
  participant B as event-bridge
  participant R as RabbitMQ (VM-2)
  participant S1 as calendar-svc
  participant S2 as wear-stats-svc

  U->>N: POST /calendar/17/worn (HTTPS)
  N->>L: proxy (X-Request-ID)
  L->>P: UPDATE outfit_calendar SET worn_at = now()
  P-->>L: COMMIT
  L-->>U: 200 (HTMX)
  P-->>B: cambio por replicación lógica (pgoutput)
  B->>R: publish closet.calendar.updated (persistente)
  R-->>B: confirm
  B->>P: acknowledge(LSN)
  par cola calendar.q
    R->>S1: entrega
    S1->>S1: INSERT processed_event + UPSERT calendar_entry (una transacción)
    S1-->>R: ack
  and cola stats.q
    R->>S2: entrega
    S2->>S2: script Lua: SET processed:<event_id> NX + HINCRBY worn
    S2-->>R: ack
  end

  alt S2 caído o con error transitorio
    R-->>R: el mensaje espera en stats.q (o se reencola con nack)
    Note over R,S2: al volver S2 procesa lo pendiente (CA-6); a los 5 intentos va a closet.dlq
  else evento inválido
    S1-->>R: nack sin reencolar
    R->>R: closet.dlx → closet.dlq
  else RabbitMQ caído
    B--xR: publish falla
    Note over B,P: sin acknowledge: PostgreSQL reenvía el cambio cuando el bridge reconecta
  end
```

## 2. Consulta del calendario (síncrona)

```mermaid
sequenceDiagram
  autonumber
  actor C as Cliente
  participant N as Nginx (VM-1)
  participant S1 as calendar-svc (VM-2)
  participant D as calendar-db

  C->>N: GET https://api.librecloset.arqweb.test/v2/calendar/today
  N->>N: genera X-Request-ID, aplica limit_req (20 r/s)
  alt dentro del límite
    N->>S1: GET /v2/calendar/today (X-Request-ID)
    S1->>D: SELECT entradas de hoy (UTC)
    D-->>S1: filas
    S1-->>N: 200 JSON (o 404 si no hay outfit hoy)
    N-->>C: 200 JSON + X-Request-ID
  else S1 caído o sin respuesta en 5 s
    N--xS1: connection refused / timeout
    N-->>C: 503 {"error":"service_unavailable","request_id":...}
    Note over N,C: el monolito sigue respondiendo 200 (CA-5)
  else más de 20 r/s
    N-->>C: 429 {"error":"too_many_requests"}
  end
```

## 3. Consulta del clima con caché e interruptor de circuito

```mermaid
sequenceDiagram
  autonumber
  actor C as Cliente
  participant N as Nginx (VM-1)
  participant S3 as weather-svc (VM-2)
  participant K as weather-cache (Redis)
  participant O as Open-Meteo

  C->>N: GET /v2/weather?lat=-25.28&lon=-57.63
  N->>S3: proxy (X-Request-ID)
  S3->>K: GET weather:-25.28:-57.63:celsius:<hoy>
  alt cache hit
    K-->>S3: pronóstico
    S3-->>C: 200 (cache=hit)
  else cache miss y circuito cerrado
    S3->>O: GET /v1/forecast (timeout 2 s, hasta 3 intentos con backoff)
    O-->>S3: pronóstico
    S3->>K: SET con TTL 30 min + copia stale 24 h
    S3-->>C: 200 (cache=miss)
  else Open-Meteo lento o caído (o circuito abierto tras 5 fallas)
    S3--xO: timeout / error
    S3->>K: GET stale:<clave>
    alt hay copia vieja
      S3-->>C: 200 (cache=stale, circuit=open)
    else no hay copia
      S3-->>C: 503 {"error":"service_unavailable"}
    end
  end
```
