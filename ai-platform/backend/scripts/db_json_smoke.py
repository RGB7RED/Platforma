import asyncio
import os
import uuid

from app import db


async def main() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for this smoke test")

    await db.init_db(database_url)
    await db.init_container_tables()

    task_id = str(uuid.uuid4())
    await db.create_task_row(
        task_id=task_id,
        user_id="smoke-user",
        description="Smoke test for JSON columns",
        status="created",
        progress=0.0,
        current_stage=None,
        codex_version="smoke",
        client_ip="127.0.0.1",
    )

    await db.append_event(
        task_id,
        "SmokeEvent",
        {"status": "failed", "container_id": "container-123"},
    )
    await db.update_task_row(
        task_id,
        {
            "status": "completed",
            "result": {"ok": True, "items": [1, 2, 3]},
            "container_state": {"status": "completed"},
        },
    )
    await db.set_container_state(task_id, {"status": "completed", "progress": 1.0})

    task_row = await db.get_task_row(task_id)
    events = await db.get_events(task_id)
    state = await db.get_container_state(task_id)

    assert isinstance(task_row["result"], dict)
    assert isinstance(task_row["container_state"], dict)
    assert events and isinstance(events[0]["payload"], dict)
    assert state and isinstance(state["state"], dict)

    pool = db._pool
    if pool is None:
        raise RuntimeError("Database pool missing during cleanup")

    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM events WHERE task_id = $1;", db._coerce_task_id(task_id))
        await conn.execute("DELETE FROM container_state WHERE task_id = $1;", db._coerce_task_id(task_id))
        await conn.execute("DELETE FROM tasks WHERE id = $1;", db._coerce_task_id(task_id))

    await db.close_db()


if __name__ == "__main__":
    asyncio.run(main())
