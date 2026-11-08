"""Pruebas unitarias de calendar-svc. Correr con: python -m pytest"""
from datetime import datetime, timezone

import pytest

from app.breaker import CircuitBreaker, CircuitOpenError
from app.handlers import InvalidEvent, plan, to_response


def envelope(kind, payload):
    return {"event_id": "00000000-0000-4000-8000-000000000001", "type": kind, "version": "1", "payload": payload}


def test_calendar_created_genera_upsert_con_fechas_parseadas():
    ops = plan(envelope("closet.calendar.created", {
        "id": 17, "date": "2026-11-21T00:00:00.000Z", "outfit_id": 5, "owner_id": 3, "worn_at": None,
    }))
    assert ops[0][0] == "upsert_entry"
    assert ops[0][1]["date"] == datetime(2026, 11, 21, tzinfo=timezone.utc)
    assert ops[0][1]["worn_at"] is None


def test_outfit_deleted_borra_el_outfit():
    assert plan(envelope("closet.outfit.deleted", {"id": 5, "name": "Oficina"})) == [("delete_outfit", {"id": 5})]


def test_evento_sin_payload_es_invalido_y_va_a_la_dlq():
    with pytest.raises(InvalidEvent):
        plan({"event_id": "x", "type": "closet.calendar.created", "payload": None})


def test_evento_de_calendario_sin_outfit_id_es_invalido():
    with pytest.raises(InvalidEvent):
        plan(envelope("closet.calendar.updated", {"id": 1, "date": "2026-11-21T00:00:00Z"}))


def test_tipos_desconocidos_se_ignoran():
    assert plan(envelope("stats.outfit.worn", {"outfit_id": 1})) == []


def test_respuesta_incluye_enlace_al_monolito():
    row = {"id": 1, "date": datetime(2026, 11, 21, tzinfo=timezone.utc), "outfit_id": 5,
           "outfit_name": "Oficina", "owner_id": 3, "worn_at": None, "notes": None}
    out = to_response(row, "https://librecloset.arqweb.test/")
    assert out["url"] == "https://librecloset.arqweb.test/outfits/5"
    assert out["worn"] is False


def test_circuito_se_abre_tras_fallas_y_se_recupera():
    now = [0.0]
    breaker = CircuitBreaker(fail_max=2, reset_timeout=10, clock=lambda: now[0])
    breaker.record_failure()
    breaker.record_failure()
    with pytest.raises(CircuitOpenError):
        breaker.before_call()
    now[0] = 11
    assert breaker.state == "half_open"
    breaker.before_call()
    breaker.record_success()
    assert breaker.state == "closed"
