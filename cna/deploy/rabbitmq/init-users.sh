#!/bin/sh
# Crea un usuario de RabbitMQ por servicio con permisos mínimos (B4).
# Uso: sh init-users.sh ruta/al/.env    (por defecto ./.env)
# Funciona tanto con docker compose como con Docker Swarm (busca el contenedor por nombre).
set -e
ENV_FILE="${1:-./.env}"
. "$ENV_FILE"

CONTAINER=$(docker ps --filter "name=rabbitmq" --format '{{.Names}}' | head -n 1)
if [ -z "$CONTAINER" ]; then
  echo "No encontré un contenedor de RabbitMQ corriendo" >&2
  exit 1
fi
ctl() { docker exec "$CONTAINER" rabbitmqctl "$@"; }

user() {
  # $1 usuario  $2 clave  $3 configurar  $4 escribir  $5 leer
  [ -z "$2" ] && { echo "Sin clave para $1, se saltea"; return; }
  ctl add_user "$1" "$2" >/dev/null 2>&1 || ctl change_password "$1" "$2" >/dev/null
  ctl set_permissions -p / "$1" "$3" "$4" "$5" >/dev/null
  echo "usuario $1 listo"
}

# event-bridge: solo publica en closet.events
user bridge "$RABBIT_BRIDGE_PASSWORD" '^$' '^closet\.events$' '^$'
# S1: solo lee su cola
user "${RABBIT_CALENDAR_USER:-calendar}" "$RABBIT_CALENDAR_PASSWORD" '^calendar\.q$' '^$' '^calendar\.q$'
# S2: lee su cola y publica stats.outfit.worn
user "${RABBIT_STATS_USER:-stats}" "$RABBIT_STATS_PASSWORD" '^stats\.q$' '^closet\.events$' '^stats\.q$'

ctl list_permissions -p /
