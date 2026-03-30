"""Database connection factory."""

from __future__ import annotations

from pathlib import Path

import aiosqlite

Connection = aiosqlite.Connection


async def open_database(db_path: Path | str) -> aiosqlite.Connection:
    """Open an aiosqlite connection with WAL mode and standard pragmas."""
    db = await aiosqlite.connect(str(db_path))
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA busy_timeout=5000")
    return db


__all__ = ["Connection", "open_database"]
