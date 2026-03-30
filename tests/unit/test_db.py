from __future__ import annotations

from pathlib import Path

import pytest

from remora.core.storage.db import open_database


@pytest.mark.asyncio
async def test_asyncdb_execute_and_fetch(tmp_path: Path) -> None:
    db = await open_database(tmp_path / "db1.sqlite")
    await db.executescript("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
    await db.execute("INSERT INTO t(name) VALUES (?)", ("a",))
    await db.commit()
    cursor = await db.execute("SELECT name FROM t WHERE id = 1")
    row = await cursor.fetchone()
    assert row is not None
    assert row["name"] == "a"
    await db.close()


@pytest.mark.asyncio
async def test_asyncdb_fetch_all(tmp_path: Path) -> None:
    db = await open_database(tmp_path / "db2.sqlite")
    await db.executescript(
        """
        CREATE TABLE t (id INTEGER PRIMARY KEY, value INTEGER);
        INSERT INTO t(value) VALUES (1);
        INSERT INTO t(value) VALUES (2);
        """
    )
    await db.commit()
    cursor = await db.execute("SELECT value FROM t ORDER BY value ASC")
    rows = await cursor.fetchall()
    assert [row["value"] for row in rows] == [1, 2]
    await db.close()


@pytest.mark.asyncio
async def test_asyncdb_insert_and_delete(tmp_path: Path) -> None:
    db = await open_database(tmp_path / "db3.sqlite")
    await db.executescript("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
    insert_cursor = await db.execute("INSERT INTO t(name) VALUES (?)", ("x",))
    await db.commit()
    row_id = int(insert_cursor.lastrowid)
    assert row_id == 1
    delete_cursor = await db.execute("DELETE FROM t WHERE id = ?", (1,))
    await db.commit()
    assert delete_cursor.rowcount == 1
    await db.close()


@pytest.mark.asyncio
async def test_asyncdb_execute_many(tmp_path: Path) -> None:
    db = await open_database(tmp_path / "db4.sqlite")
    await db.executescript("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
    await db.executemany(
        "INSERT INTO t(name) VALUES (?)",
        [("a",), ("b",)],
    )
    await db.commit()
    cursor = await db.execute("SELECT name FROM t ORDER BY id ASC")
    rows = await cursor.fetchall()
    assert [row["name"] for row in rows] == ["a", "b"]
    await db.close()
