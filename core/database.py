"""Bounded compatibility database layer for independent plugin stores."""

from __future__ import annotations

import asyncio
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

import aiosqlite

DB_DIR = Path(__file__).resolve().parent.parent / "data" / "databases"


class DatabaseError(RuntimeError):
    pass


class Database:
    """Small bounded SQLite adapter retained for plugin-specific databases.

    These stores remain independent during the incremental platform migration.
    The adapter provides the same basic safety contract as the canonical store:
    WAL, foreign keys, bounded contention, explicit transactions, integrity
    checks, verified backups, and bounded shutdown.
    """

    BUSY_TIMEOUT_MS = 5000
    BACKUP_TIMEOUT_SECONDS = 30.0
    MAX_BACKUP_BYTES = 2 * 1024 * 1024 * 1024

    _instances: dict[str, "Database"] = {}

    def __init__(self, name: str):
        self.name = name
        self.path = DB_DIR / f"{name}.db"
        self.conn: aiosqlite.Connection | None = None
        self.lock = asyncio.Lock()

    @classmethod
    def get(cls, name: str) -> "Database":
        if not name or "/" in name or "\\" in name or name in {".", ".."}:
            raise DatabaseError("Invalid database name")
        if name not in cls._instances:
            cls._instances[name] = cls(name)
        return cls._instances[name]

    async def _connect(self):
        if self.conn is not None:
            return
        async with self.lock:
            if self.conn is not None:
                return
            DB_DIR.mkdir(parents=True, exist_ok=True)
            try:
                conn = await aiosqlite.connect(self.path)
                await conn.execute("PRAGMA journal_mode=WAL")
                await conn.execute("PRAGMA synchronous=NORMAL")
                await conn.execute("PRAGMA foreign_keys=ON")
                await conn.execute(f"PRAGMA busy_timeout={self.BUSY_TIMEOUT_MS}")
                await conn.commit()
                self.conn = conn
            except (sqlite3.Error, OSError) as exc:
                raise DatabaseError(f"Unable to open database {self.name}: {exc}") from exc

    async def init_schema(self, ddl: str):
        await self._connect()
        async with self.lock:
            try:
                await self.conn.executescript(ddl)
                await self.conn.commit()
            except sqlite3.Error as exc:
                await self.conn.rollback()
                raise DatabaseError(f"Schema initialization failed for {self.name}: {exc}") from exc

    async def execute(self, sql: str, parameters: tuple[Any, ...] = ()):
        await self._connect()
        async with self.lock:
            try:
                cursor = await self.conn.execute(sql, parameters)
                await self.conn.commit()
                return cursor
            except sqlite3.Error as exc:
                await self.conn.rollback()
                raise DatabaseError(f"Database write failed for {self.name}: {exc}") from exc

    async def transaction(self, statements: list[tuple[str, tuple[Any, ...]]]) -> None:
        await self._connect()
        async with self.lock:
            try:
                await self.conn.execute("BEGIN")
                for sql, parameters in statements:
                    await self.conn.execute(sql, parameters)
                await self.conn.commit()
            except sqlite3.Error as exc:
                await self.conn.rollback()
                raise DatabaseError(f"Database transaction failed for {self.name}: {exc}") from exc

    async def fetchall(self, sql: str, parameters: tuple[Any, ...] = ()):
        await self._connect()
        async with self.lock:
            try:
                async with self.conn.execute(sql, parameters) as cursor:
                    return await cursor.fetchall()
            except sqlite3.Error as exc:
                raise DatabaseError(f"Database read failed for {self.name}: {exc}") from exc

    async def fetchone(self, sql: str, parameters: tuple[Any, ...] = ()):
        await self._connect()
        async with self.lock:
            try:
                async with self.conn.execute(sql, parameters) as cursor:
                    return await cursor.fetchone()
            except sqlite3.Error as exc:
                raise DatabaseError(f"Database read failed for {self.name}: {exc}") from exc

    async def integrity_check(self) -> bool:
        row = await self.fetchone("PRAGMA integrity_check")
        return bool(row and str(row[0]).lower() == "ok")

    async def foreign_key_check(self):
        return await self.fetchall("PRAGMA foreign_key_check")

    async def database_size(self) -> int:
        total = 0
        for suffix in ("", "-wal", "-shm"):
            try:
                total += Path(str(self.path) + suffix).stat().st_size
            except FileNotFoundError:
                pass
        return total

    async def checkpoint(self, *, truncate: bool = False) -> None:
        await self._connect()
        mode = "TRUNCATE" if truncate else "PASSIVE"
        async with self.lock:
            try:
                await self.conn.execute(f"PRAGMA wal_checkpoint({mode})")
            except sqlite3.Error as exc:
                raise DatabaseError(f"WAL checkpoint failed for {self.name}: {exc}") from exc

    async def backup(self, destination: str | Path) -> Path:
        await self._connect()
        target = Path(destination).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        if target == self.path:
            raise DatabaseError("Backup destination must differ from source")
        if await self.database_size() > self.MAX_BACKUP_BYTES:
            raise DatabaseError("Database exceeds configured backup size bound")
        if not await self.integrity_check():
            raise DatabaseError("Refusing backup of an integrity-failed database")

        temp: Path | None = None
        async with self.lock:
            try:
                fd, raw_temp = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
                os.close(fd)
                temp = Path(raw_temp)
                target_conn = sqlite3.connect(temp)
                try:
                    await self.conn.commit()
                    await asyncio.wait_for(self.conn.backup(target_conn), timeout=self.BACKUP_TIMEOUT_SECONDS)
                    target_conn.commit()
                    check = target_conn.execute("PRAGMA integrity_check").fetchone()
                    if not check or str(check[0]).lower() != "ok":
                        raise DatabaseError("Backup integrity check failed")
                finally:
                    target_conn.close()
                os.replace(temp, target)
                temp = None
                return target
            except (sqlite3.Error, asyncio.TimeoutError, OSError) as exc:
                raise DatabaseError(f"Database backup failed for {self.name}: {exc}") from exc
            finally:
                if temp is not None:
                    try:
                        temp.unlink()
                    except FileNotFoundError:
                        pass

    async def close(self):
        if self.conn is None:
            return
        async with self.lock:
            if self.conn is None:
                return
            conn, self.conn = self.conn, None
            try:
                await conn.execute("PRAGMA optimize")
                await conn.close()
            finally:
                self.conn = None

    @classmethod
    async def close_all(cls):
        databases = list(cls._instances.values())
        if not databases:
            return
        tasks = [asyncio.create_task(db.close()) for db in databases]
        done, pending = await asyncio.wait(tasks, timeout=2.0)
        for task in done:
            try:
                task.result()
            except Exception:
                pass
        for task in pending:
            task.cancel()
