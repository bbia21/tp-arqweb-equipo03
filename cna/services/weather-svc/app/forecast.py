"""Funciones puras de weather-svc (sin red ni Redis) para poder probarlas."""
from datetime import date

# Las mismas variables diarias que pide Libre Closet en src/weather/weather.service.ts
DAILY = "weathercode,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
UNITS = ("celsius", "fahrenheit")


class BadRequest(Exception):
    pass


def validate(lat: float, lon: float, days: int, unit: str) -> None:
    if not -90 <= lat <= 90:
        raise BadRequest("lat tiene que estar entre -90 y 90")
    if not -180 <= lon <= 180:
        raise BadRequest("lon tiene que estar entre -180 y 180")
    if not 1 <= days <= 14:
        raise BadRequest("days tiene que estar entre 1 y 14")
    if unit not in UNITS:
        raise BadRequest("unit tiene que ser celsius o fahrenheit")


def cache_key(lat: float, lon: float, unit: str, today: date) -> str:
    # Coordenadas redondeadas a 2 decimales (~1 km), igual que el monolito
    return f"weather:{lat:.2f}:{lon:.2f}:{unit}:{today.isoformat()}"


def build_params(lat: float, lon: float, unit: str) -> dict:
    return {
        "latitude": f"{lat:.2f}",
        "longitude": f"{lon:.2f}",
        "daily": DAILY,
        "temperature_unit": unit,
        "timezone": "auto",
        "forecast_days": 14,
    }


def parse(data: dict, days: int) -> list[dict]:
    """Convierte la respuesta columnar de Open-Meteo en una lista por día."""
    daily = data.get("daily") or {}
    dates = daily.get("time") or []
    result = []
    for i, day in enumerate(dates[:days]):
        result.append({
            "date": day,
            "weathercode": daily.get("weathercode", [None] * len(dates))[i],
            "temperature_max": daily.get("temperature_2m_max", [None] * len(dates))[i],
            "temperature_min": daily.get("temperature_2m_min", [None] * len(dates))[i],
            "precipitation_probability_max": daily.get("precipitation_probability_max", [None] * len(dates))[i],
        })
    return result
