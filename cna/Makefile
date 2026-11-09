# Uso (en VM-1, dentro del repositorio):
#   make up       despliega todo (CDC, RabbitMQ, S1, S2, S3, event-bridge, gateway) en un comando
#   make down     baja la parte cloud native (el monolito sigue corriendo)
#   make status   estado de los contenedores en los dos nodos
#   make test     pruebas automatizadas de todos los servicios
#   make lint-contracts   valida OpenAPI con Spectral (AsyncAPI: AsyncAPI Studio, F5-E4)
.PHONY: up down status lint-contracts test test-bridge test-stats test-calendar test-weather

up:
	bash deploy/up.sh

down:
	bash deploy/down.sh

status:
	@echo "== VM-1 ($$(hostname))"; docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}"
	@echo; echo "== VM-2 (cna-node1)"; docker --context cna-node1 ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}"

test: test-bridge test-stats test-calendar test-weather

test-bridge:
	docker run --rm -v "$(CURDIR)/services/event-bridge":/app -w /app node:22-alpine sh -c "npm ci --silent && npm test"

test-stats:
	docker run --rm -v "$(CURDIR)/services/wear-stats-svc":/app -w /app node:22-alpine sh -c "npm ci --silent && npm test"

test-calendar:
	docker run --rm -v "$(CURDIR)/services/calendar-svc":/app -w /app python:3.12-slim sh -c "pip install -q -r requirements.txt pytest && python -m pytest -q -p no:cacheprovider"

test-weather:
	docker run --rm -v "$(CURDIR)/services/weather-svc":/app -w /app python:3.12-slim sh -c "pip install -q -r requirements.txt pytest && python -m pytest -q -p no:cacheprovider"

lint-contracts:
	docker run --rm -v "$(CURDIR)/contracts":/work -w /work stoplight/spectral:6 lint "*.openapi.yaml"
