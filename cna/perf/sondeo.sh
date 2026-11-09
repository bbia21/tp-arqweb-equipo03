#!/usr/bin/env bash
# Sondeo para medir MTTR en los experimentos de caos (Fase 7).
# Pide una URL cada 0,5 s y escribe una línea solo cuando cambia el código HTTP.
# Al cortar con Ctrl+C muestra cuánto tiempo estuvo caído (MTTR).
#
#   bash perf/sondeo.sh https://api.librecloset.arqweb.test/v2/calendar/today
#
set -u
URL="${1:?uso: sondeo.sh URL}"
anterior="" ; caida_desde="" ; total_caido=0

resumen() {
  echo
  if [ -n "$caida_desde" ]; then echo "Sigue caído (desde hace $(( $(date +%s%3N) - caida_desde )) ms)"; fi
  echo "Tiempo total caído: ${total_caido} ms"
  exit 0
}
trap resumen INT

while true; do
  codigo=$(curl -sk -o /dev/null -w '%{http_code}' --max-time 2 "$URL" || true)
  ahora=$(date +%s%3N)
  # 200 y 404 (no hay outfit hoy) cuentan como "responde bien"; 5xx o 000 (sin respuesta) como caído
  case "$codigo" in 2??|404) estado=ok ;; *) estado=caido ;; esac
  if [ "$codigo" != "$anterior" ]; then
    echo "$(date +%H:%M:%S.%3N)  HTTP $codigo  ($estado)"
    if [ "$estado" = caido ] && [ -z "$caida_desde" ]; then caida_desde=$ahora; fi
    if [ "$estado" = ok ] && [ -n "$caida_desde" ]; then
      dur=$(( ahora - caida_desde )); total_caido=$(( total_caido + dur )); caida_desde=""
      echo "            -> recuperado en ${dur} ms"
    fi
    anterior=$codigo
  fi
  sleep 0.5
done
