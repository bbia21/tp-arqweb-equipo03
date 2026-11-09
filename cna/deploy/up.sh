#!/usr/bin/env bash
# Despliegue completo de la parte cloud native en un solo comando (CA-7, B5): make up
#
# Se corre en VM-1, desde el repositorio. Requisitos previos (infraestructura, una sola vez):
#   - VM-1 con el monolito del TP I corriendo (/srv/libre-closet) y Nginx instalado
#   - VM-2 con Docker, alcanzable por SSH sin contraseña desde VM-1 (ssh-copy-id)
#
# Qué hace, en orden:
#   1. arma los .env (genera contraseñas al azar si faltan; nunca pisa las existentes)
#   2. configura el CDC en el PostgreSQL del monolito (idempotente)
#   3. levanta RabbitMQ en VM-2 y crea colas, DLQ y usuarios
#   4. levanta S1, S2 y S3 en VM-2 y el event-bridge en VM-1, esperando que estén healthy
#   5. instala la configuración del gateway si cambió y hace una prueba de humo por el 443
set -euo pipefail

CNA="$(cd "$(dirname "$0")/.." && pwd)"
VM1="$CNA/deploy/vm1"
VM2="$CNA/deploy/vm2"
VM2_SSH="${VM2_SSH:-admins@192.168.56.11}"
VM2_IP="${VM2_SSH#*@}"
VM1_IP="${VM1_IP:-192.168.56.10}"
CONTEXT="cna-node1"
INICIO=$(date +%s)

export IMAGE_TAG="1.0.0-$(git -C "$CNA" rev-parse --short HEAD 2>/dev/null || echo dev)"

paso() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
ok() { printf '\033[1;32m    OK\033[0m %s\n' "$*"; }
falla() { printf '\033[1;31m    ERROR\033[0m %s\n' "$*" >&2; exit 1; }
rand() { openssl rand -hex 12; }
leer() { grep -E "^$2=" "$1" 2>/dev/null | head -n1 | cut -d= -f2- || true; }
asegurar() { grep -qE "^$2=" "$1" || echo "$2=$3" >> "$1"; }
psql_monolito() { docker exec closet-postgres psql -U closet -d closet -tAq -v ON_ERROR_STOP=1 -c "$1"; }

paso "Versión de imágenes: $IMAGE_TAG"

# ---------------------------------------------------------------- 1. .env
paso "1/7 Variables de entorno y secretos"
if [ ! -f "$VM2/.env" ]; then
  # Si VM-2 ya tenía un .env, se reutiliza (las bases ya creadas usan esas contraseñas)
  ssh -o BatchMode=yes "$VM2_SSH" 'cat ~/cna/deploy/vm2/.env 2>/dev/null' > "$VM2/.env" || true
fi
touch "$VM2/.env" && chmod 600 "$VM2/.env"
asegurar "$VM2/.env" VM1_IP "$VM1_IP"
asegurar "$VM2/.env" RABBIT_ADMIN_PASSWORD "$(rand)"
asegurar "$VM2/.env" RABBIT_BRIDGE_PASSWORD "$(rand)"
asegurar "$VM2/.env" RABBIT_CALENDAR_USER calendar
asegurar "$VM2/.env" RABBIT_CALENDAR_PASSWORD "$(rand)"
asegurar "$VM2/.env" RABBIT_STATS_USER stats
asegurar "$VM2/.env" RABBIT_STATS_PASSWORD "$(rand)"
asegurar "$VM2/.env" CALENDAR_DB_PASSWORD "$(rand)"
asegurar "$VM2/.env" MONOLITH_URL ""
asegurar "$VM2/.env" SVC_EMAIL ""
asegurar "$VM2/.env" SVC_PASSWORD ""
asegurar "$VM2/.env" GRAFANA_ADMIN_PASSWORD "$(rand)"

CDC=$(leer "$VM1/.env" CDC_PASSWORD)
[ -n "$CDC" ] || CDC=$(leer /srv/libre-closet/.env CDC_PASSWORD)
[ -n "$CDC" ] || CDC=$(rand)
cat > "$VM1/.env" <<EOF
CDC_PASSWORD=$CDC
RABBIT_USER=bridge
RABBIT_PASSWORD=$(leer "$VM2/.env" RABBIT_BRIDGE_PASSWORD)
RABBIT_HOST=$VM2_IP
EOF
chmod 600 "$VM1/.env"
ok "deploy/vm1/.env y deploy/vm2/.env listos (no se versionan)"

# ---------------------------------------------------------------- 2. CDC
paso "2/7 CDC en el PostgreSQL del monolito"
docker inspect -f '{{.State.Health.Status}}' closet-postgres 2>/dev/null | grep -q healthy \
  || falla "el monolito no está corriendo: cd /srv/libre-closet && docker compose up -d"
[ "$(psql_monolito 'SHOW wal_level')" = "logical" ] || falla "PostgreSQL no tiene wal_level=logical"

if [ -z "$(psql_monolito "SELECT 1 FROM pg_roles WHERE rolname='cna_cdc'")" ]; then
  psql_monolito "CREATE ROLE cna_cdc WITH LOGIN REPLICATION PASSWORD '$CDC'"
else
  psql_monolito "ALTER ROLE cna_cdc WITH LOGIN REPLICATION PASSWORD '$CDC'"
fi
psql_monolito "GRANT SELECT ON outfit, outfit_calendar TO cna_cdc"
[ -n "$(psql_monolito "SELECT 1 FROM pg_publication WHERE pubname='cna_pub'")" ] \
  || psql_monolito "CREATE PUBLICATION cna_pub FOR TABLE outfit, outfit_calendar"
psql_monolito "ALTER TABLE outfit REPLICA IDENTITY FULL; ALTER TABLE outfit_calendar REPLICA IDENTITY FULL"
# Defecto de una migración de Libre Closet en PostgreSQL: garment.color quedó smallint
if [ "$(psql_monolito "SELECT data_type FROM information_schema.columns WHERE table_name='garment' AND column_name='color'")" = "smallint" ]; then
  psql_monolito "ALTER TABLE garment ALTER COLUMN color TYPE varchar(255) USING color::varchar(255)"
  ok "corregido garment.color (smallint -> varchar)"
fi
ok "rol cna_cdc, publicación cna_pub y REPLICA IDENTITY FULL"

# ---------------------------------------------------------------- 3. VM-2
paso "3/7 Conexión con VM-2 ($VM2_SSH)"
ssh -o BatchMode=yes -o ConnectTimeout=5 "$VM2_SSH" true 2>/dev/null \
  || falla "no hay SSH sin contraseña a VM-2. Corré una vez: ssh-copy-id $VM2_SSH"
docker context inspect "$CONTEXT" >/dev/null 2>&1 \
  || docker context create "$CONTEXT" --docker "host=ssh://$VM2_SSH" >/dev/null
DC2=(docker --context "$CONTEXT" compose -p vm2 -f "$VM2/docker-compose.yml" --env-file "$VM2/.env")
DC1=(docker compose -p vm1 -f "$VM1/docker-compose.yml" --env-file "$VM1/.env")
DCO=(docker --context "$CONTEXT" compose -p obs -f "$CNA/observability/docker-compose.yml" --env-file "$VM2/.env")
ok "contexto de Docker '$CONTEXT'"

# ---------------------------------------------------------------- 4. RabbitMQ
paso "4/7 RabbitMQ en VM-2: broker, colas, DLQ y usuarios"
"${DC2[@]}" up -d --build --wait rabbitmq
"${DC1[@]}" build --quiet
ADMIN=$(leer "$VM2/.env" RABBIT_ADMIN_PASSWORD)
docker run --rm -e AMQP_URL="amqp://admin:$ADMIN@$VM2_IP:5672" "event-bridge:$IMAGE_TAG" node src/setup-topology.js
DOCKER_CONTEXT="$CONTEXT" sh "$CNA/deploy/rabbitmq/init-users.sh" "$VM2/.env" >/dev/null
ok "exchange closet.events, colas calendar.q / stats.q, DLQ y usuarios bridge / calendar / stats"

# ---------------------------------------------------------------- 5. Servicios
paso "5/7 Microservicios en VM-2 (S1, S2, S3 y sus almacenes)"
# Se construyen solo los servicios (RabbitMQ ya se construyó en el paso 4): si se reconstruye
# dos veces, la etiqueta pasa a otra imagen y el contenedor de RabbitMQ queda mostrando un id.
"${DC2[@]}" build calendar-svc wear-stats-svc weather-svc
"${DC2[@]}" up -d --wait
ok "servicios healthy en VM-2"

paso "6/7 Observabilidad en VM-2 (Prometheus, Loki, Promtail, Grafana) y event-bridge en VM-1"
"${DCO[@]}" up -d --build
"${DC1[@]}" up -d --build --wait
ok "observabilidad levantada y event-bridge healthy"

# ---------------------------------------------------------------- 6. Gateway
paso "7/7 Gateway Nginx y prueba de humo por el 443"
cambio=0
cmp -s "$VM1/nginx/api-librecloset" /etc/nginx/sites-available/api-librecloset || cambio=1
for f in "$VM1"/nginx/api-routes/*.conf; do
  cmp -s "$f" "/etc/nginx/snippets/api-routes/$(basename "$f")" || cambio=1
done
if [ "$cambio" = 1 ]; then
  sudo mkdir -p /etc/nginx/snippets/api-routes
  sudo cp "$VM1/nginx/api-librecloset" /etc/nginx/sites-available/api-librecloset
  sudo cp "$VM1"/nginx/api-routes/*.conf /etc/nginx/snippets/api-routes/
  sudo ln -sf /etc/nginx/sites-available/api-librecloset /etc/nginx/sites-enabled/api-librecloset
  sudo nginx -t && sudo systemctl reload nginx
  ok "configuración del gateway actualizada"
else
  ok "configuración del gateway sin cambios"
fi

api() { curl -sk -o /dev/null -w '%{http_code}' --resolve api.librecloset.arqweb.test:443:127.0.0.1 "https://api.librecloset.arqweb.test$1"; }
mono=$(curl -sk -o /dev/null -w '%{http_code}' --resolve librecloset.arqweb.test:443:127.0.0.1 https://librecloset.arqweb.test/)
printf '    monolito  /                 -> %s\n' "$mono"
printf '    S1  /v2/calendar             -> %s\n' "$(api /v2/calendar)"
printf '    S2  /v2/stats/outfits/top    -> %s\n' "$(api /v2/stats/outfits/top)"
printf '    S3  /v2/weather              -> %s\n' "$(api '/v2/weather?lat=-25.28&lon=-57.63&days=1')"

printf '\n\033[1;32mListo en %s segundos.\033[0m\n' "$(( $(date +%s) - INICIO ))"
printf '    Grafana:    ssh -p 2223 -L 3000:localhost:3000 -L 9090:localhost:9090 admins@127.0.0.1  (desde Windows)\n'
printf '                luego http://localhost:3000  (usuario admin, clave: GRAFANA_ADMIN_PASSWORD en deploy/vm2/.env)\n'
