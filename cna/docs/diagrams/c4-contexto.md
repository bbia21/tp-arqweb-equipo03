# C4 nivel 1 · Contexto (F5-E5)

Notación C4 dibujada con un diagrama de flujo de Mermaid (personas en azul oscuro, el sistema en azul,
sistemas externos en gris).

```mermaid
flowchart LR
  U["<b>Usuaria</b><br/>[Persona]<br/>Organiza su guardarropa,<br/>arma outfits y los agenda"]
  C["<b>Cliente de la API</b><br/>[Persona o sistema]<br/>curl, k6 u otra app"]
  S["<b>Libre Closet Cloud Native</b><br/>[Sistema]<br/>Monolito + microservicios<br/>(calendario, estadísticas, clima)<br/>detrás de un gateway único"]
  OM["<b>Open-Meteo</b><br/>[Sistema externo]<br/>Pronóstico del clima"]
  NO["<b>Nominatim</b><br/>[Sistema externo]<br/>Nombre del lugar"]

  U -- "Usa la web<br/>HTTPS 443" --> S
  C -- "Consulta /v2/*<br/>HTTPS 443" --> S
  S -- "Pide pronósticos<br/>HTTPS" --> OM
  S -- "Pide el nombre del lugar<br/>HTTPS" --> NO

  classDef persona fill:#08427b,stroke:#052e56,color:#ffffff
  classDef sistema fill:#1168bd,stroke:#0b4884,color:#ffffff
  classDef externo fill:#8a8a8a,stroke:#6b6b6b,color:#ffffff
  class U,C persona
  class S sistema
  class OM,NO externo
```

Todo el tráfico externo entra por el puerto 443 de VM-1 (CA-4). El sistema depende de dos servicios
externos; solo Open-Meteo está protegido con caché e interruptor de circuito (S3).
