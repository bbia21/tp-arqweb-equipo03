# Pruebas de todos los servicios con un solo comando: make test
# No hace falta tener Node ni Python instalados: corre cada suite dentro de un contenedor.
.PHONY: test test-bridge test-stats test-calendar test-weather

test: test-bridge test-stats test-calendar test-weather

test-bridge:
	docker run --rm -v "$(CURDIR)/services/event-bridge":/app -w /app node:22-alpine sh -c "npm ci --silent && npm test"

test-stats:
	docker run --rm -v "$(CURDIR)/services/wear-stats-svc":/app -w /app node:22-alpine sh -c "npm ci --silent && npm test"

test-calendar:
	docker run --rm -v "$(CURDIR)/services/calendar-svc":/app -w /app python:3.12-slim sh -c "pip install -q -r requirements.txt pytest && python -m pytest -q -p no:cacheprovider"

test-weather:
	docker run --rm -v "$(CURDIR)/services/weather-svc":/app -w /app python:3.12-slim sh -c "pip install -q -r requirements.txt pytest && python -m pytest -q -p no:cacheprovider"
