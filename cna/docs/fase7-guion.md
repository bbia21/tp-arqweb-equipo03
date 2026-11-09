# Fase 7 — Guion de observabilidad, caos, carga y seguridad

Guion para el lunes y el martes. Cada bloque dice **dónde** se corre (VM-1, VM-2 o Windows),
**qué** se ve si sale bien y **qué captura** guardar (los nombres coinciden con `figuras/` del informe).

Convenciones:

- Salvo que diga otra cosa, todo se corre **en VM-1**, dentro de `~/tp-arqweb-equipo03/cna`.
- Para no escribir tanto, primero cargá estos atajos en la terminal de VM-1 (hay que repetirlo si
  abrís otra terminal):

```bash
cd ~/tp-arqweb-equipo03/cna
export N2="docker --context cna-node1"
export API=https://api.librecloset.arqweb.test
alias dc2='docker --context cna-node1 compose -p vm2 -f deploy/vm2/docker-compose.yml --env-file deploy/vm2/.env'
```

- Antes de cada experimento, anotá la hora (`date +%T`): sirve para buscar en Grafana y en los logs.
- Si la compu se apaga a mitad de camino: prendé las dos VMs (ver el procedimiento de siempre) y
  corré `make status`. Si algo quedó caído, `make up` lo vuelve a levantar.

---

## 0. Puesta en marcha (lunes, ~20 min)

1. Liberá disco en VM-1 (el paquete de observabilidad agrega imágenes):

   ```bash
   df -h /
   docker image prune -af        # borra imágenes que ningún contenedor usa
   docker builder prune -af
   ```

2. Levantá todo (ahora `make up` también levanta Prometheus, Loki, Promtail y Grafana):

   ```bash
   make up
   make status
   ```

   Tenés que ver, además de lo de siempre, `obs-prometheus-1`, `obs-loki-1`, `obs-promtail-1`,
   `obs-grafana-1` en VM-2 y `promtail` en VM-1.

3. Abrí el túnel para ver Grafana y Prometheus **desde Windows** (PowerShell nuevo, dejalo abierto):

   ```powershell
   ssh -p 2223 -L 3000:localhost:3000 -L 9090:localhost:9090 admins@127.0.0.1
   ```

   - Grafana: <http://localhost:3000> — usuario `admin`. La contraseña la ves en VM-1 con
     `grep GRAFANA_ADMIN_PASSWORD deploy/vm2/.env`.
   - Prometheus: <http://localhost:9090/targets> — todos los *targets* tienen que estar en **UP**.

   Si un target de los servicios está DOWN, mirá `docker --context cna-node1 logs obs-prometheus-1 | tail`.
   Si `event-bridge` está DOWN, revisá que VM-2 pueda llegar a `192.168.56.10:8080`
   (en VM-2: `curl -s 192.168.56.10:8080/metrics | head -3`). Si no llega, en VM-1:
   `sudo ufw allow from 192.168.56.11 to any port 8080 proto tcp`.

4. Generá un poco de tráfico para que los gráficos no estén vacíos:

   ```bash
   for i in $(seq 1 60); do
     curl -sk -o /dev/null $API/v2/calendar
     curl -sk -o /dev/null "$API/v2/weather?lat=-25.3&lon=-57.63"
     curl -sk -o /dev/null $API/v2/stats/outfits/top
     sleep 0.5
   done
   ```

   Y en la web de Libre Closet agendá 2 o 3 outfits y marcá alguno como usado.

### Capturas de observabilidad

| Captura | Qué mostrar |
|---|---|
| **F7-E9** | Grafana → Dashboards → *Libre Closet CNA · RED por servicio*. Que se vean los paneles de tasa, errores, latencia p50/p95/p99 y colas. Rango: últimos 15 min. |
| **F7-E10** | En VM-1: `curl -sk -D - -o /dev/null $API/v2/calendar \| grep -i x-request-id`. Copiá el valor, pegalo en la caja *request_id* arriba del tablero. El panel de logs muestra la línea del **gateway** y la de **calendar-svc** con el mismo id. |
| **F7-E11** | No hay trazas distribuidas (OpenTelemetry quedó fuera de alcance): se reemplaza por la correlación. Grafana → Explore → Loki → `{job="docker"} \|= "<event_id>"` usando un `event_id` de un evento real (sale en `docker logs event-bridge \| tail`). Se ve el mismo evento en event-bridge, calendar-svc y wear-stats-svc. |
| **F7-E12** | Se saca durante X1b (ver abajo): Prometheus → *Alerts* con `ServicioCaido` en **FIRING**. Con X3b sale `MensajesEnDLQ`. |

> Para la defensa: el `request_id` lo genera Nginx y viaja en el header `X-Request-ID` hasta el
> servicio; en los eventos, el bridge pone un `request_id` nuevo en el sobre y cada consumidor lo
> escribe en sus logs. Por eso se puede seguir una operación entre máquinas sin tener tracing.

---

## 1. Medir el MTTR

Para cada experimento dejá corriendo el sondeo en **otra terminal de VM-1**:

```bash
cd ~/tp-arqweb-equipo03/cna
bash perf/sondeo.sh https://api.librecloset.arqweb.test/v2/calendar/today
```

Escribe una línea cada vez que cambia el código HTTP y, al cortar con **Ctrl+C**, el tiempo total
caído. Ese número va en la columna *MTTR* de la tabla de la sección 14 del informe.
Si el experimento es de otro servicio, cambiá la URL (ej. `/v2/stats/outfits/top`).

---

## 2. Experimentos de caos (lunes)

### X1 — Se cae S1 y vuelve solo (F7-E1)

Hipótesis: si se muere calendar-svc, el monolito sigue andando, `/v2/calendar` responde 503 en JSON y
el contenedor se reinicia solo.

```bash
# terminal 1: el sondeo de la sección 1
# terminal 2:
date +%T
$N2 exec vm2-calendar-svc-1 sh -c 'kill 1'          # mata el proceso principal
curl -sk $API/v2/calendar ; echo                     # durante la caída: 503 JSON con request_id
curl -sk -o /dev/null -w '%{http_code}\n' https://librecloset.arqweb.test/   # el monolito: 200/302
sleep 10; $N2 ps --filter name=calendar-svc          # "Up X seconds (healthy)" -> se recreó solo
```

Captura **F7-E1**: las dos terminales lado a lado (sondeo con la caída y la recuperación + el 503 JSON +
el `docker ps` con el contenedor recién levantado). El MTTR sale del sondeo.

**X1b (para la alerta, F7-E12):** `$N2 stop vm2-calendar-svc-1`, esperá ~45 s, captura de
Prometheus → Alerts con `ServicioCaido` en FIRING. Después `$N2 start vm2-calendar-svc-1`.

### X2 — S2 detenido 2 minutos, no se pierde nada (F7-E2)

Hipótesis: mientras wear-stats-svc está apagado, los eventos esperan en `stats.q`; al volver los
procesa todos y el contador sube exactamente lo que se marcó.

```bash
OUTFIT=1      # poné el id de un outfit que tengas agendado
curl -sk $API/v2/stats/outfits/$OUTFIT ; echo                       # anotá worn_count ANTES
$N2 stop vm2-wear-stats-svc-1 ; date +%T
```

Ahora, en la web, marcá como **usado** ese outfit en varios días del calendario (la consigna dice 20;
si es mucho, hacé 10 y anotalo así en el informe). Mientras tanto mirá la cola:

```bash
$N2 exec vm2-rabbitmq-1 rabbitmqctl list_queues name messages_ready messages_unacknowledged
```

`stats.q` va subiendo. Pasados los 2 minutos:

```bash
$N2 start vm2-wear-stats-svc-1 ; date +%T
sleep 15
$N2 exec vm2-rabbitmq-1 rabbitmqctl list_queues name messages_ready messages_unacknowledged   # stats.q en 0
curl -sk $API/v2/stats/outfits/$OUTFIT ; echo                       # worn_count = ANTES + los que marcaste
```

Captura **F7-E2**: la cola con N mensajes, la cola en 0 y el contador antes/después.

### X3 — S2 muere en medio de un mensaje: se reentrega y cuenta una sola vez (F7-E3)

Hipótesis: si el proceso muere después de aplicar el evento pero antes del `ack`, RabbitMQ lo vuelve
a entregar y la idempotencia por `event_id` evita contarlo dos veces.

Para poder matar el proceso justo en ese momento, S2 tiene una espera opcional antes del `ack`
(`ACK_DELAY_MS`, por defecto 0). La activamos solo para este experimento:

```bash
STATS_ACK_DELAY_MS=15000 dc2 up -d wear-stats-svc
curl -sk $API/v2/stats/outfits/$OUTFIT ; echo                       # anotá worn_count ANTES
```

En la web marcá **un** uso de ese outfit. Enseguida:

```bash
$N2 logs -f vm2-wear-stats-svc-1      # esperá la línea "evento aplicado; ack en 15000 ms (X3)" y cortá con Ctrl+C
$N2 kill vm2-wear-stats-svc-1         # lo matamos antes del ack
$N2 exec vm2-rabbitmq-1 rabbitmqctl list_queues name messages_ready messages_unacknowledged   # stats.q: 1 listo
$N2 start vm2-wear-stats-svc-1
sleep 20
$N2 logs vm2-wear-stats-svc-1 | grep -E '"result":"(processed|duplicate)"' | tail -3   # aparece "duplicate"
curl -sk $API/v2/stats/outfits/$OUTFIT ; echo                       # worn_count = ANTES + 1 (no + 2)
STATS_ACK_DELAY_MS=0 dc2 up -d wear-stats-svc                        # volver a la normalidad
```

Captura **F7-E3**: el log con `duplicate`, la cola con el mensaje reentregado y el contador +1.

**X3b (alerta de DLQ, opcional para F7-E12):** publicar un mensaje inválido y ver cómo va a la DLQ.

```bash
ADMIN=$(grep RABBIT_ADMIN_PASSWORD deploy/vm2/.env | cut -d= -f2)
$N2 exec vm2-rabbitmq-1 wget -qO- --header 'content-type: application/json' --post-data \
  '{"properties":{"type":"closet.calendar.updated"},"routing_key":"closet.calendar.updated","payload":"esto no es json","payload_encoding":"string"}' \
  "http://admin:$ADMIN@localhost:15672/api/exchanges/%2F/closet.events/publish"; echo   # tiene que decir {"routed":true}
sleep 5; $N2 exec vm2-rabbitmq-1 rabbitmqctl list_queues name messages | grep dlq
```

Al minuto aparece `MensajesEnDLQ` en FIRING. Para limpiar: `$N2 exec vm2-rabbitmq-1 rabbitmqctl purge_queue closet.dlq`.

### X4 — Se apaga VM-2 entera (F7-E4)

Hipótesis: el monolito sigue sirviendo; las rutas `/v2` responden 503 JSON; los cambios hechos mientras
VM-2 está apagada quedan retenidos en el slot de replicación y se entregan solos al volver.

1. Sondeo en una terminal de VM-1 (sección 1). Anotá la hora.
2. **En Windows (PowerShell):**

   ```powershell
   $vbox = "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe"
   & $vbox controlvm "cna-node1" poweroff
   ```

3. En VM-1, mientras VM-2 está apagada:

   ```bash
   curl -sk -o /dev/null -w 'monolito %{http_code}\n' https://librecloset.arqweb.test/
   curl -sk $API/v2/calendar ; echo                        # 503 JSON
   docker logs --tail 5 event-bridge                        # reintenta conectar a RabbitMQ
   docker exec closet-postgres psql -U closet -d closet -c \
     "SELECT slot_name, active, pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), confirmed_flush_lsn)) AS retenido FROM pg_replication_slots"
   ```

   En la web, agendá un outfit nuevo (este es el cambio que tiene que llegar después).

4. Prendé VM-2: `& $vbox startvm "cna-node1" --type headless`. Esperá 1–2 min y, en VM-1:

   ```bash
   make status
   curl -sk $API/v2/calendar ; echo                        # aparece el outfit agendado con VM-2 apagada
   ```

   Si algún servicio no volvió solo, `make up` (y anotalo como hallazgo).

Captura **F7-E4**: el 503 + el monolito en 200 + el slot con WAL retenido + el outfit que llegó después.
MTTR: desde que arrancás VM-2 hasta que el sondeo vuelve a 200 (incluye el arranque de la VM).
Después de esto conviene volver a abrir el túnel de Grafana.

### X5 — 2 s de latencia hacia Internet: timeout, reintentos y circuito de S3 (F7-E5)

Hipótesis: con Open-Meteo lento, weather-svc corta a los 2 s, reintenta, abre el circuito y responde
con la copia vieja (`"cache":"stale"`) o con 503, sin quedarse colgado.

Se hace **en VM-2** (`ssh -p 2223 admins@127.0.0.1`). La latencia se aplica solo al puerto 443 de
salida, así no se pone lento el SSH:

```bash
IF=$(ip route | awk '/default/ {print $5; exit}') ; echo $IF      # suele ser enp0s3
sudo tc qdisc add dev $IF root handle 1: prio
sudo tc qdisc add dev $IF parent 1:3 handle 30: netem delay 2000ms
sudo tc filter add dev $IF protocol ip parent 1:0 prio 3 u32 match ip dport 443 0xffff flowid 1:3
```

Volvé a VM-1 y pedí el clima de un lugar que ya estaba en caché y de uno nuevo:

```bash
docker --context cna-node1 exec vm2-weather-cache-1 redis-cli --scan --pattern 'weather:*' | xargs -r docker --context cna-node1 exec vm2-weather-cache-1 redis-cli del   # borra la caché fresca, deja la "stale"
for i in 1 2 3 4 5 6; do
  /usr/bin/time -f '%e s' curl -sk "$API/v2/weather?lat=-25.3&lon=-57.63" | head -c 160; echo
done
/usr/bin/time -f '%e s' curl -sk "$API/v2/weather?lat=-16.5&lon=-68.15" ; echo   # lugar nuevo: 503 JSON
curl -s http://192.168.56.11:8003/readyz ; echo                                   # "circuit":"open"
```

Lo esperable: las primeras tardan unos segundos (timeout + reintentos) y devuelven `"cache":"stale"`;
cuando el circuito se abre, responden al instante. Si el puerto 8003 no responde, probá 8004
(desde que S3 escala, Docker elige un puerto del rango 8003–8005).

**Quitá la latencia en VM-2** (importante):

```bash
sudo tc qdisc del dev $IF root
```

A los 30 s el circuito pasa a *half_open* y con el siguiente pedido se cierra. Captura **F7-E5**:
los tiempos, el `stale`, el 503 del lugar nuevo y el `readyz` con el circuito abierto.

---

## 3. Pruebas de carga con k6 (martes, ~45 min)

Se corren en VM-1 contra el gateway. Antes, **cerrá el navegador y lo que no uses** (la compu calienta).

```bash
mkdir -p perf/resultados
K6="docker run --rm --network host --add-host librecloset.arqweb.test:127.0.0.1 --add-host api.librecloset.arqweb.test:127.0.0.1 -v $PWD/perf:/perf grafana/k6"
read -p "Email de tu usuario de Libre Closet: " EMAIL
read -s -p "Contraseña: " PASSWORD; echo
```

### Monolito vs S1 (F7-E6)

Cada corrida hace 60 s contra `GET /calendar` del monolito y después 60 s contra `GET /v2/calendar`.

```bash
$K6 run -e ESCENARIO=calendario -e VUS=10 -e EMAIL="$EMAIL" -e PASSWORD="$PASSWORD" \
  --summary-export /perf/resultados/calendario-10.json /perf/load.js
$K6 run -e ESCENARIO=calendario -e VUS=50 -e EMAIL="$EMAIL" -e PASSWORD="$PASSWORD" \
  --summary-export /perf/resultados/calendario-50.json /perf/load.js
```

Mientras corre la de 50, en otra terminal: `docker stats --no-stream` y
`docker --context cna-node1 stats --no-stream` → captura **F7-E8**.

En el resumen de k6 mirá `http_req_duration{destino:monolito}` y `{destino:s1}`: p50, p95, p99 y
`http_reqs` (req/s). Con 50 usuarios vas a ver `limitadas` (respuestas 429): es el `limit_req` de
20 r/s del gateway funcionando, y vale como hallazgo. Captura **F7-E6**: los dos resúmenes.

### Escalar S3 de 1 a 3 réplicas (F7-E7)

```bash
$K6 run -e ESCENARIO=clima -e VUS=30 --summary-export /perf/resultados/clima-1.json /perf/load.js
dc2 up -d --scale weather-svc=3 --no-recreate weather-svc
$N2 ps --filter name=weather-svc                     # 3 contenedores, puertos 8003, 8004 y 8005
$K6 run -e ESCENARIO=clima -e VUS=30 --summary-export /perf/resultados/clima-3.json /perf/load.js
tail -n 200 /var/log/nginx/api-access.log | grep -o '"upstream":"[^"]*"' | sort | uniq -c   # reparto entre las 3
dc2 up -d --scale weather-svc=1 weather-svc           # volver a 1
```

Captura **F7-E7**: el `ps` con 3 réplicas, el reparto en el log de Nginx y los dos resúmenes.
Si casi todo sale de la caché, la mejora va a ser chica: eso también es una conclusión válida
(el cuello de botella no está en S3 sino en la red / el gateway).

Para llenar la tabla del informe, los números salen de los JSON:

```bash
for f in perf/resultados/*.json; do
  echo "== $f"
  jq -r '.metrics | to_entries[] | select(.key|startswith("http_req_duration{")) |
    "\(.key)  p50=\(.value."p(50)"|floor)ms  p95=\(.value."p(95)"|floor)ms  p99=\(.value."p(99)"|floor)ms"' "$f"
  jq -r '"req/s=\(.metrics.http_reqs.rate|floor)  limitadas=\(.metrics.limitadas.count // 0)"' "$f"
done
```

(Si no tenés `jq`: `sudo apt install -y jq`.)

---

## 4. Seguridad (martes, ~40 min)

### Trivy y SBOM (F7-E13)

Usamos Trivy **0.69.3** fijado a propósito: en marzo de 2026 la cadena de distribución de Trivy fue
comprometida y las imágenes 0.69.4, 0.69.5 y 0.69.6 (y `latest` de esos días) traían código malicioso.
Fijar una versión conocida y no usar `latest` es justamente la práctica que pide la Fase 7.

Se corre en VM-2 (ahí están las imágenes de los servicios). La primera vez baja la base de
vulnerabilidades (~500 MB):

```bash
TAG=$(grep IMAGE_TAG deploy/vm2/.env | cut -d= -f2) ; echo $TAG
TRIVY="docker --context cna-node1 run --rm -v /var/run/docker.sock:/var/run/docker.sock -v trivy-cache:/root/.cache aquasec/trivy:0.69.3"
mkdir -p docs/seguridad
for img in calendar-svc wear-stats-svc weather-svc cna-rabbitmq; do
  $TRIVY image --quiet --severity HIGH,CRITICAL --format table $img:$TAG | tee docs/seguridad/trivy-$img.txt
  $TRIVY image --quiet --format cyclonedx $img:$TAG > docs/seguridad/sbom-$img.cdx.json
done
# event-bridge está en VM-1:
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock -v trivy-cache:/root/.cache aquasec/trivy:0.69.3 \
  image --quiet --severity HIGH,CRITICAL event-bridge:$(grep IMAGE_TAG deploy/vm1/.env | cut -d= -f2) | tee docs/seguridad/trivy-event-bridge.txt
ls -lh docs/seguridad
```

Captura **F7-E13**: la tabla de uno de los servicios + el `ls` de los SBOM. En el informe anotá cuántas
HIGH/CRITICAL hay por imagen. Si aparecen, casi siempre son del sistema base: la respuesta es
"se corrige actualizando la imagen base y reconstruyendo", no hace falta arreglarlas ahora.
Al final: `docker --context cna-node1 volume rm trivy-cache` si necesitás disco.

### Rotación de la credencial de `svc-cna` sin reconstruir ni cortar (F7-E14)

calendar-svc lee la contraseña del usuario de servicio de `SVC_PASSWORD`, pero si existe el archivo
`/tmp/svc_password` dentro del contenedor, usa ese. Cuando el archivo cambia, descarta la sesión y
vuelve a entrar con la clave nueva. No se reconstruye la imagen ni se reinicia el contenedor.

1. Generá la clave nueva (en VM-1):

   ```bash
   NUEVA=$(openssl rand -hex 12) ; echo "$NUEVA"
   ```

2. Cambiá la contraseña de `svc-cna` en Libre Closet: iniciá sesión con ese usuario en el navegador
   (ventana privada) y cambiala desde el perfil. Si la app no tiene esa opción, hacelo por la base
   (primero mirá cómo se llama la columna):

   ```bash
   docker exec closet-postgres psql -U closet -d closet -c '\d "user"'
   HASH=$(docker run --rm python:3.12-slim sh -c "pip -q install bcrypt >/dev/null 2>&1 && python -c \"import bcrypt;print(bcrypt.hashpw(b'$NUEVA', bcrypt.gensalt(10)).decode())\"")
   docker exec closet-postgres psql -U closet -d closet -c "UPDATE \"user\" SET password='$HASH' WHERE email='EMAIL_DE_SVC_CNA'"
   ```

3. Entregale la clave nueva al servicio en caliente:

   ```bash
   date +%T
   printf '%s' "$NUEVA" | $N2 exec -i vm2-calendar-svc-1 sh -c 'cat > /tmp/svc_password'
   ```

4. Probalo: agendá un outfit en la web y mirá el log de S1:

   ```bash
   $N2 logs --since 2m vm2-calendar-svc-1 | grep -E 'rotada|outfit|verific'
   $N2 ps --filter name=calendar-svc        # "Up X hours": no se reinició
   ```

   Tiene que aparecer `credencial del usuario de servicio rotada: se renueva la sesión` y la
   verificación del outfit sin errores.

5. Dejalo persistente para el próximo `make up` (si no, al recrearse volvería a la clave vieja):

   ```bash
   sed -i "s/^SVC_PASSWORD=.*/SVC_PASSWORD=$NUEVA/" deploy/vm2/.env
   unset NUEVA HASH
   ```

Captura **F7-E14**: el log con "rotada", el `ps` sin reinicio y la verificación OK.
(La clave no tiene que verse en la captura.)

---

## 5. Tiempo de rollback (para el A5)

El rollback del Strangler es sacar las rutas `/v2` del gateway; el monolito no se toca.

```bash
sudo mkdir -p /root/rutas-respaldo
time ( sudo mv /etc/nginx/snippets/api-routes/*.conf /root/rutas-respaldo/ && sudo nginx -t -q && sudo systemctl reload nginx )
curl -sk -o /dev/null -w '%{http_code}\n' $API/v2/calendar      # 404: ya no se enruta
time ( sudo mv /root/rutas-respaldo/*.conf /etc/nginx/snippets/api-routes/ && sudo nginx -t -q && sudo systemctl reload nginx )
curl -sk -o /dev/null -w '%{http_code}\n' $API/v2/calendar      # 200 otra vez
```

El `real` del primer `time` es el tiempo de rollback que va en `docs/A5-migracion-riesgos.md`.

---

## 6. Cierre

```bash
make status
git status --short | grep "\.env$" || echo "OK: sin secretos"
git add -A && git commit -m "Fase 7: observabilidad, caos, carga y seguridad" && git push
git tag v2.0.0 && git push origin v2.0.0
```
