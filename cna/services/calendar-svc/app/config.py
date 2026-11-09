"""Configuración solo por variables de entorno (Twelve-Factor, factor III)."""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    service_name: str = "calendar-svc"

    # Base de datos propia del servicio (database per service, ADR-009)
    database_url: str = "postgresql://calendar:calendar@calendar-db:5432/calendar"

    # RabbitMQ
    amqp_url: str = "amqp://guest:guest@rabbitmq:5672/"
    queue: str = "calendar.q"

    # Enlace público hacia las páginas del monolito
    monolith_public_url: str = "https://librecloset.arqweb.test"

    # Verificación opcional contra el monolito (si MONOLITH_URL está vacío, no se usa)
    monolith_url: str = ""
    monolith_verify_tls: bool = False
    svc_email: str = ""
    svc_password: str = ""
    # Rotación sin reinicio (C4): si este archivo existe, su contenido reemplaza a SVC_PASSWORD
    svc_password_file: str = "/tmp/svc_password"
    monolith_timeout_seconds: float = 1.0

    # Zona horaria para "hoy"
    timezone: str = "America/Asuncion"


settings = Settings()
