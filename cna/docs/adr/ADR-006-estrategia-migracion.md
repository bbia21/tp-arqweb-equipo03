# ADR-006: Estrategia de migración e integración con el monolito

**Estatus:** Aceptado (consultado con el docente el 07/11/2026)

## Contexto

Libre Closet (v0.6.0) debe seguir operando mientras se extraen funcionalidades. La consigna exige
integrarse sin modificar su código. A diferencia de BookStack, Libre Closet **no tiene Webhooks ni una
API REST con token**: solo expone páginas HTML para personas (NestJS + Handlebars + HTMX).

## Decisión

1. Patrón **Strangler Fig**: el monolito sigue atendiendo prendas, outfits y usuarios; alrededor se
   construyen servicios que toman el calendario, las estadísticas de uso y el clima.
2. Integración asíncrona por **CDC (Change Data Capture)**: el `event-bridge` lee el WAL de PostgreSQL
   mediante replicación lógica (`pgoutput`, publicación `cna_pub`, slot `cna_slot`) y publica cada cambio
   de `outfit` y `outfit_calendar` como evento en RabbitMQ. Reemplaza a los Webhooks.
3. Integración síncrona puntual: S1 consulta `GET /outfits/{id}` del monolito con un usuario de servicio
   de solo lectura (`svc-cna`), para verificar que un outfit existe.
4. El `event-bridge` corre en VM-1, al lado de PostgreSQL, con un rol (`cna_cdc`) que solo tiene
   `REPLICATION` y `SELECT` sobre las dos tablas publicadas. La base nunca sale de VM-1.

## Alternativas descartadas

| Alternativa | Por qué se descartó |
| --- | --- |
| Agregar un módulo de Webhooks a Libre Closet | Prohibido por la consigna (modificar el código del monolito) |
| Polling periódico de la base o de las páginas HTML | Pierde cambios entre consultas, agrega carga y la rúbrica B4 lo penaliza |
| `mirror` de Nginx para copiar los POST a un servicio | No ve la respuesta: no sabe el `id` de lo creado ni si la operación falló |
| Debezium + Kafka Connect | Resuelve lo mismo, pero consume más de 1 GB de RAM (JVM) en VMs de 4 GB |

## Consecuencias

**Positivas**
- Cero cambios en el código del monolito; se captura todo cambio, venga de la web o de cualquier otro lado.
- Entrega garantizada: el slot de replicación retiene los cambios hasta que el bridge confirma (CA-6).
- Cada evento trae la fila completa (`REPLICA IDENTITY FULL`): los servicios no necesitan consultar al monolito.

**Negativas**
- El bridge depende del **esquema interno** de Libre Closet: si una versión nueva renombra columnas, hay que
  ajustar `envelope.js` (capa anticorrupción).
- El `X-Request-ID` de la petición original **no viaja en el WAL**: el bridge genera uno nuevo y la traza de
  una edición empieza en el bridge, no en el gateway.
- Si el bridge queda detenido mucho tiempo, el slot retiene WAL y crece el disco de VM-1 (se monitorea).
