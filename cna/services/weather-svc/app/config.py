"""Configuración solo por variables de entorno (Twelve-Factor, factor III)."""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    service_name: str = "weather-svc"
    redis_url: str = "redis://weather-cache:6379/0"
    open_meteo_url: str = "https://api.open-meteo.com/v1/forecast"
    # Mismo TTL por defecto que Libre Closet (WEATHER_CACHE_TTL_MS = 30 min)
    cache_ttl_seconds: int = 1800
    # Copia "vieja" para responder si Open-Meteo está caído
    stale_ttl_seconds: int = 86400
    timeout_seconds: float = 2.0
    retries: int = 3
    breaker_fail_max: int = 5
    breaker_reset_seconds: float = 30.0


settings = Settings()
