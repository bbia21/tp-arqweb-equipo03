# C4 nivel 2 · Contenedores (F5-E6)

Notación C4 dibujada con un diagrama de flujo de Mermaid: cada recuadro claro es un nodo (VM), los
rectángulos azules son contenedores y los cilindros, almacenes de datos.

```mermaid
flowchart TB
  U["<b>Usuaria / cliente de la API</b><br/>[Persona]"]

  subgraph VM1["VM-1 · librecloset · 192.168.56.10"]
    NG["<b>Nginx 1.24</b> · gateway :443<br/>TLS 1.3 · rate limit<br/>X-Request-ID"]
    LC["<b>Libre Closet 0.6.0</b><br/>NestJS · 127.0.0.1:3000"]
    PG[("<b>PostgreSQL 16</b><br/>wal_level=logical")]
    EB["<b>event-bridge</b><br/>Node 22 · CDC"]
  end

  subgraph VM2["VM-2 · cna-node1 · 192.168.56.11"]
    RB["<b>RabbitMQ 4.1</b><br/>closet.events · DLQ · :5672"]
    S1["<b>S1 calendar-svc</b><br/>Python · :8001"]
    S2["<b>S2 wear-stats-svc</b><br/>Node · :8002"]
    S3["<b>S3 weather-svc</b><br/>Python · :8003"]
    D1[("calendar-db<br/>PostgreSQL")]
    D2[("stats-db<br/>Redis AOF")]
    D3[("weather-cache<br/>Redis")]
  end

  OM["<b>Open-Meteo</b><br/>[Sistema externo]"]

  U -->|"HTTPS 443"| NG
  NG -->|"/"| LC
  LC -->|"SQL"| PG
  PG -->|"WAL"| EB
  NG -->|"/v2/calendar"| S1
  NG -->|"/v2/stats"| S2
  NG -->|"/v2/weather"| S3
  EB -->|"AMQP"| RB
  RB -->|"calendar.q"| S1
  RB -->|"stats.q"| S2
  S1 --> D1
  S2 --> D2
  S3 --> D3
  S3 -->|"HTTPS"| OM

  classDef persona fill:#08427b,stroke:#052e56,color:#ffffff
  classDef contenedor fill:#438dd5,stroke:#2e6295,color:#ffffff
  classDef datos fill:#2b6ca3,stroke:#1d4a70,color:#ffffff
  classDef externo fill:#8a8a8a,stroke:#6b6b6b,color:#ffffff
  class U persona
  class NG,LC,EB,RB,S1,S2,S3 contenedor
  class PG,D1,D2,D3 datos
  class OM externo
  style VM1 fill:#f4f8fc,stroke:#2e6295,color:#0b2a4a
  style VM2 fill:#f4f8fc,stroke:#2e6295,color:#0b2a4a
```

Ningún contenedor de VM-2 se conecta a PostgreSQL del monolito; solo el event-bridge, dentro de VM-1
(ADR-006, ADR-009). Además, S1 puede consultar al monolito (`GET /outfits/{id}` con el usuario de
servicio `svc-cna`) para verificar que un outfit existe. En VM-2, UFW y la cadena `DOCKER-USER` solo
aceptan conexiones desde 192.168.56.10.
