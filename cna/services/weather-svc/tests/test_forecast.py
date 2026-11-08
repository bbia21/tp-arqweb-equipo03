"""Pruebas unitarias de weather-svc. Correr con: python -m pytest"""
from datetime import date

import pytest

from app.breaker import CircuitBreaker, CircuitOpenError
from app.forecast import BadRequest, build_params, cache_key, parse, validate

OPEN_METEO = {
    "daily": {
        "time": ["2026-11-08", "2026-11-09", "2026-11-10"],
        "weathercode": [1, 61, 3],
        "temperature_2m_max": [33.1, 28.4, 30.0],
        "temperature_2m_min": [22.0, 20.5, 21.3],
        "precipitation_probability_max": [10, 80, 20],
    }
}


def test_parse_convierte_columnas_en_dias_y_respeta_el_limite():
    days = parse(OPEN_METEO, 2)
    assert len(days) == 2
    assert days[1] == {
        "date": "2026-11-09", "weathercode": 61, "temperature_max": 28.4,
        "temperature_min": 20.5, "precipitation_probability_max": 80,
    }


def test_cache_key_redondea_coordenadas():
    assert cache_key(-25.28123, -57.63499, "celsius", date(2026, 11, 8)) == "weather:-25.28:-57.63:celsius:2026-11-08"


def test_parametros_iguales_a_los_del_monolito():
    params = build_params(-25.28, -57.63, "celsius")
    assert params["daily"] == "weathercode,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
    assert params["forecast_days"] == 14
    assert params["timezone"] == "auto"


@pytest.mark.parametrize("lat,lon,days,unit", [(91, 0, 7, "celsius"), (0, 0, 15, "celsius"), (0, 0, 7, "kelvin")])
def test_validacion_rechaza_parametros_fuera_de_rango(lat, lon, days, unit):
    with pytest.raises(BadRequest):
        validate(lat, lon, days, unit)


def test_circuito_abierto_rechaza_llamadas():
    breaker = CircuitBreaker(fail_max=1, reset_timeout=60, clock=lambda: 0.0)
    breaker.record_failure()
    with pytest.raises(CircuitOpenError):
        breaker.before_call()
