#!/usr/bin/env bash
# Baja la parte cloud native (no toca el monolito del TP I): make down
# Con BORRAR_DATOS=1 también borra los volúmenes (RabbitMQ, base de S1, Redis de S2).
set -euo pipefail
CNA="$(cd "$(dirname "$0")/.." && pwd)"
CONTEXT="cna-node1"
VOL=()
[ "${BORRAR_DATOS:-0}" = 1 ] && VOL=(--volumes)

docker compose -p vm1 -f "$CNA/deploy/vm1/docker-compose.yml" --env-file "$CNA/deploy/vm1/.env" down "${VOL[@]}"
docker --context "$CONTEXT" compose -p vm2 -f "$CNA/deploy/vm2/docker-compose.yml" --env-file "$CNA/deploy/vm2/.env" down "${VOL[@]}"
echo "Parte cloud native detenida. El monolito sigue corriendo."
