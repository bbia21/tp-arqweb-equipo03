# A5 · Plan de migración y matriz de riesgos

## Orden de extracción (de menor a mayor riesgo)

| Paso | Servicio | Por qué en este orden | Criterio de "hecho" |
| --- | --- | --- | --- |
| 1 | S3 weather-svc | No toca datos: solo envuelve Open-Meteo | `/v2/weather` responde por el gateway; `miss` → `hit` (F6-E6, F6-E7); 3+ pruebas pasan |
| 2 | event-bridge + RabbitMQ | Es la base de los servicios asíncronos; no cambia nada visible | Un cambio en el calendario aparece en el broker (F6-E11, F6-E12) |
| 3 | S2 wear-stats-svc | Solo lee eventos y cuenta; si falla, nadie pierde datos | Contador correcto e idempotente (F6-E5); mensaje inválido a la DLQ (F6-E13) |
| 4 | S1 calendar-svc | Duplica datos del monolito y lo consulta: el más acoplado | Un outfit agendado aparece en `/v2/calendar` en < 5 s (F6-E4, CA-3) |

## Reversión en menos de 1 minuto

Cada ruta del gateway vive en su propio archivo (`/etc/nginx/snippets/api-routes/*.conf`).
Para desactivar una ruta y volver a lo que ofrece el monolito:

```bash
sudo mv /etc/nginx/snippets/api-routes/calendar.conf /etc/nginx/snippets/api-routes/calendar.conf.off
sudo nginx -t && sudo systemctl reload nginx      # /v2/calendar pasa a 404 JSON
# El calendario sigue disponible en el monolito: https://librecloset.arqweb.test/calendar
```

Para volver a activarla, el mismo `mv` al revés. Medido: ____ segundos (completar al cronometrarlo).

## Matriz de riesgos

Probabilidad (P) e impacto (I) de 1 a 3; nivel = P × I.

| Riesgo | P | I | Nivel | Mitigación |
| --- | --- | --- | --- | --- |
| Consistencia eventual visible: `/v2/calendar` muestra datos viejos | 2 | 1 | 2 | Objetivo < 5 s medido (CA-3); la web del monolito siempre muestra lo actual |
| RAM insuficiente (4 GB por VM) | 2 | 3 | 6 | Límites de memoria en cada contenedor (suma < 3,2 GB por nodo); `docker stats` en C2 |
| Latencia de red entre VM-1 y VM-2 | 1 | 2 | 2 | Red interna de VirtualBox; `keepalive` en los upstream; timeouts del gateway de 2 s / 5 s |
| Secretos compartidos o expuestos | 2 | 3 | 6 | `.env` fuera del repositorio, generados al azar por `make up`; un usuario de RabbitMQ por servicio; rol `cna_cdc` limitado a dos tablas |
| Punto único de falla en el gateway (Nginx en VM-1) | 1 | 3 | 3 | Riesgo aceptado (un solo punto de entrada por diseño); `nginx -t` antes de cada recarga; `restart` automático del servicio |
| Cambio de esquema en una versión nueva de Libre Closet rompe el CDC | 2 | 3 | 6 | Versión fijada (`0.6.0`); traducción aislada en `envelope.js`; eventos inválidos van a la DLQ en vez de trabar las colas |
| Open-Meteo caído o sin internet en el laboratorio | 2 | 2 | 4 | Caché de 30 min, copia vieja de 24 h, circuito y 503 JSON (S3) |
| El slot de replicación retiene WAL si el bridge queda detenido | 1 | 3 | 3 | `restart: unless-stopped`; alerta si el bridge no publica; monitorear disco de VM-1 |
