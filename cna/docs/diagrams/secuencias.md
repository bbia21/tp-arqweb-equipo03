# Diagramas de secuencia (F5-E7)

## 1. Marcar un outfit como usado → calendario y estadísticas (asíncrono)

```mermaid
sequenceDiagram
  autonumber
  actor U as Usuaria
  participant L as Nginx + Libre Closet<br/>(VM-1)
  participant P as PostgreSQL<br/>(VM-1)
  participant B as event-bridge<br/>(VM-1)
  participant R as RabbitMQ<br/>(VM-2)
  participant S1 as calendar-svc<br/>(VM-2)
  participant S2 as wear-stats-svc<br/>(VM-2)

  U->>L: marcar outfit como usado (HTTPS)
  L->>P: UPDATE outfit_calendar SET worn_at
  L-->>U: 200
  P-->>B: cambio por replicación lógica
  B->>R: publica closet.calendar.updated
  R-->>B: confirmación (publisher confirm)
  B->>P: confirma la posición del WAL
  R->>S1: entrega desde calendar.q
  S1->>S1: guarda event_id y la entrada
  S1-->>R: ack
  R->>S2: entrega desde stats.q
  S2->>S2: suma 1 si el event_id es nuevo
  S2-->>R: ack

  alt S2 caído
    Note over R,S2: el mensaje espera en stats.q y se procesa cuando S2 vuelve
  else evento inválido
    S2-->>R: nack sin reencolar
    Note over R: el mensaje pasa a closet.dlq
  else RabbitMQ caído
    B--xR: no puede publicar
    Note over B,P: sin confirmación, PostgreSQL reenvía el cambio al reconectar
  end
```

## 2. Consulta del calendario (síncrono)

```mermaid
sequenceDiagram
  autonumber
  actor C as Cliente
  participant N as Nginx<br/>(VM-1)
  participant S1 as calendar-svc<br/>(VM-2)
  participant D as calendar-db<br/>(VM-2)

  C->>N: GET /v2/calendar/today
  Note over N: genera X-Request-ID y aplica el límite de 20 r/s
  alt dentro del límite y S1 disponible
    N->>S1: GET /v2/calendar/today
    S1->>D: SELECT entradas de hoy
    D-->>S1: filas
    S1-->>N: 200 JSON
    N-->>C: 200 JSON + X-Request-ID
  else S1 caído o sin respuesta en 5 s
    N--xS1: conexión rechazada / timeout
    N-->>C: 503 JSON service_unavailable
    Note over C,N: el monolito sigue respondiendo 200 (CA-5)
  else más de 20 r/s
    N-->>C: 429 JSON too_many_requests
  end
```

## 3. Consulta del clima con caché e interruptor de circuito

```mermaid
sequenceDiagram
  autonumber
  actor C as Cliente
  participant S3 as weather-svc<br/>(VM-2, vía Nginx)
  participant K as weather-cache<br/>(Redis)
  participant O as Open-Meteo<br/>(externo)

  C->>S3: GET /v2/weather?lat=-25.28&lon=-57.63
  S3->>K: busca el pronóstico de hoy
  alt está en caché
    K-->>S3: pronóstico
    S3-->>C: 200 (cache = hit)
  else no está y el circuito está cerrado
    S3->>O: GET /v1/forecast (timeout 2 s, 3 intentos)
    O-->>S3: pronóstico
    S3->>K: guarda 30 min + copia vieja 24 h
    S3-->>C: 200 (cache = miss)
  else Open-Meteo falla o el circuito está abierto
    S3--xO: timeout / error
    S3->>K: busca la copia vieja
    alt hay copia vieja
      S3-->>C: 200 (cache = stale)
    else no hay copia
      S3-->>C: 503 JSON service_unavailable
    end
  end
```
