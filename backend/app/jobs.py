from datetime import datetime, timezone

from .db import get_connection


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_job(job_id: str, source_path: str) -> None:
    now = _now()
    conn = get_connection()
    conn.execute(
        "INSERT INTO jobs (id, status, source_path, created_at, updated_at) VALUES (?, 'queued', ?, ?, ?)",
        (job_id, source_path, now, now),
    )
    conn.commit()
    conn.close()


def get_job(job_id: str) -> dict | None:
    conn = get_connection()
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def claim_next_queued_job() -> dict | None:
    """Atomically claims the oldest queued job so multiple worker replicas
    never process the same job twice (SQLite serializes writers, so this
    single UPDATE is race-free without needing Postgres's SKIP LOCKED)."""
    conn = get_connection()
    row = conn.execute("SELECT id FROM jobs WHERE status = 'queued' ORDER BY created_at LIMIT 1").fetchone()
    if not row:
        conn.close()
        return None

    job_id = row["id"]
    cur = conn.execute(
        "UPDATE jobs SET status = 'processing', updated_at = ? WHERE id = ? AND status = 'queued'",
        (_now(), job_id),
    )
    conn.commit()
    conn.close()

    if cur.rowcount == 0:
        return None  # another worker won the race
    return get_job(job_id)


def update_job(job_id: str, **fields) -> None:
    fields["updated_at"] = _now()
    columns = ", ".join(f"{k} = ?" for k in fields)
    values = [*fields.values(), job_id]
    conn = get_connection()
    conn.execute(f"UPDATE jobs SET {columns} WHERE id = ?", values)
    conn.commit()
    conn.close()
