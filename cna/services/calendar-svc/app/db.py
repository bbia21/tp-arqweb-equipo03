"""Acceso a la base propia de calendar-svc (no toca la base de Libre Closet)."""
import asyncpg

SCHEMA = """
CREATE TABLE IF NOT EXISTS outfit (
    id        integer PRIMARY KEY,
    name      text,
    owner_id  integer
);
CREATE TABLE IF NOT EXISTS calendar_entry (
    id         integer PRIMARY KEY,
    date       timestamptz NOT NULL,
    outfit_id  integer NOT NULL,
    owner_id   integer,
    worn_at    timestamptz,
    notes      text,
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS calendar_entry_owner_date ON calendar_entry (owner_id, date);
-- Idempotencia: cada event_id se procesa una sola vez (ADR-010)
CREATE TABLE IF NOT EXISTS processed_event (
    event_id     uuid PRIMARY KEY,
    processed_at timestamptz NOT NULL DEFAULT now()
);
"""


async def connect(url: str) -> asyncpg.Pool:
    pool = await asyncpg.create_pool(url, min_size=1, max_size=5)
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA)
    return pool


async def apply(pool: asyncpg.Pool, event_id: str, operations: list[tuple[str, dict]]) -> bool:
    """Aplica las operaciones en una transacción. Devuelve False si el evento ya se había procesado."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            inserted = await conn.fetchval(
                "INSERT INTO processed_event (event_id) VALUES ($1) ON CONFLICT DO NOTHING RETURNING event_id",
                event_id,
            )
            if inserted is None:
                return False
            for op, data in operations:
                if op == "upsert_entry":
                    await conn.execute(
                        """
                        INSERT INTO calendar_entry (id, date, outfit_id, owner_id, worn_at, notes, updated_at)
                        VALUES ($1, $2, $3, $4, $5, $6, now())
                        ON CONFLICT (id) DO UPDATE SET
                            date = EXCLUDED.date, outfit_id = EXCLUDED.outfit_id,
                            owner_id = EXCLUDED.owner_id, worn_at = EXCLUDED.worn_at,
                            notes = EXCLUDED.notes, updated_at = now()
                        """,
                        data["id"], data["date"], data["outfit_id"], data["owner_id"], data["worn_at"], data["notes"],
                    )
                elif op == "delete_entry":
                    await conn.execute("DELETE FROM calendar_entry WHERE id = $1", data["id"])
                elif op == "upsert_outfit":
                    await conn.execute(
                        """
                        INSERT INTO outfit (id, name, owner_id) VALUES ($1, $2, $3)
                        ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, owner_id = EXCLUDED.owner_id
                        """,
                        data["id"], data["name"], data["owner_id"],
                    )
                elif op == "delete_outfit":
                    await conn.execute("DELETE FROM outfit WHERE id = $1", data["id"])
                    await conn.execute("DELETE FROM calendar_entry WHERE outfit_id = $1", data["id"])
    return True


async def list_entries(pool: asyncpg.Pool, owner_id: int | None, start, end) -> list[dict]:
    rows = await pool.fetch(
        """
        SELECT e.id, e.date, e.outfit_id, o.name AS outfit_name, e.owner_id, e.worn_at, e.notes
        FROM calendar_entry e LEFT JOIN outfit o ON o.id = e.outfit_id
        WHERE ($1::int IS NULL OR e.owner_id = $1) AND e.date >= $2 AND e.date < $3
        ORDER BY e.date, e.id
        """,
        owner_id, start, end,
    )
    return [dict(r) for r in rows]


async def ping(pool: asyncpg.Pool) -> bool:
    try:
        await pool.fetchval("SELECT 1")
        return True
    except Exception:  # noqa: BLE001
        return False
