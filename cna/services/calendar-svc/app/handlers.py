"""Traduce cada evento a operaciones sobre la base propia del servicio.

Son funciones puras (sin base ni red) para poder probarlas con pytest.
"""
from datetime import datetime


class InvalidEvent(Exception):
    """El evento no se puede procesar nunca: va directo a la DLQ."""


def _parse_ts(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise InvalidEvent(f"fecha inválida: {value}") from exc


def _require_int(payload: dict, field: str) -> int:
    value = payload.get(field)
    if value is None:
        raise InvalidEvent(f"falta {field}")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise InvalidEvent(f"{field} no es un número: {value}") from exc


def plan(event: dict) -> list[tuple[str, dict]]:
    """Devuelve la lista de operaciones a aplicar para este evento."""
    if not isinstance(event, dict) or "type" not in event or "event_id" not in event:
        raise InvalidEvent("el mensaje no tiene el sobre de evento (type, event_id)")
    payload = event.get("payload")
    if not isinstance(payload, dict):
        raise InvalidEvent("payload vacío o inválido")

    kind = event["type"]
    if kind in ("closet.calendar.created", "closet.calendar.updated"):
        date = _parse_ts(payload.get("date"))
        if date is None:
            raise InvalidEvent("falta date")
        return [(
            "upsert_entry",
            {
                "id": _require_int(payload, "id"),
                "date": date,
                "outfit_id": _require_int(payload, "outfit_id"),
                "owner_id": payload.get("owner_id"),
                "worn_at": _parse_ts(payload.get("worn_at")),
                "notes": payload.get("notes"),
            },
        )]
    if kind == "closet.calendar.deleted":
        return [("delete_entry", {"id": _require_int(payload, "id")})]
    if kind in ("closet.outfit.created", "closet.outfit.updated"):
        return [(
            "upsert_outfit",
            {"id": _require_int(payload, "id"), "name": payload.get("name"), "owner_id": payload.get("owner_id")},
        )]
    if kind == "closet.outfit.deleted":
        return [("delete_outfit", {"id": _require_int(payload, "id")})]
    # Otros tipos no le interesan a este servicio: se confirman sin hacer nada
    return []


def to_response(row: dict, public_url: str) -> dict:
    """Formato de salida de GET /v2/calendar."""
    return {
        "id": row["id"],
        "date": row["date"].isoformat() if row["date"] else None,
        "outfit_id": row["outfit_id"],
        "outfit_name": row.get("outfit_name"),
        "owner_id": row.get("owner_id"),
        "worn": row.get("worn_at") is not None,
        "worn_at": row["worn_at"].isoformat() if row.get("worn_at") else None,
        "notes": row.get("notes"),
        "url": f"{public_url.rstrip('/')}/outfits/{row['outfit_id']}",
    }
