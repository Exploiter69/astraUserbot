import asyncio
from pathlib import Path

import aiosqlite

DB_DIR = Path(__file__).resolve().parent.parent / "data" / "databases"


class Database:
    _instances: dict[str, "Database"] = {}

    def __init__(self, name: str):
        self.name = name
        self.path = DB_DIR / f"{name}.db"
        self.conn: aiosqlite.Connection | None = None
        self.lock = asyncio.Lock()

    @classmethod
    def get(cls, name: str) -> "Database":
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
            conn = await aiosqlite.connect(self.path)
            await conn.execute("PRAGMA journal_mode=WAL;")
            await conn.execute("PRAGMA synchronous=NORMAL;")
            await conn.execute("PRAGMA foreign_keys=ON;")
            await conn.execute("PRAGMA busy_timeout=5000;")
            await conn.commit()
            self.conn = conn

    async def init_schema(self, ddl: str):
        await self._connect()
        async with self.lock:
            await self.conn.executescript(ddl)
            await self.conn.commit()

    async def execute(self, sql: str, parameters: tuple = ()):
        await self._connect()
        async with self.lock:
            cursor = await self.conn.execute(sql, parameters)
            await self.conn.commit()
            return cursor

    async def fetchall(self, sql: str, parameters: tuple = ()):
        await self._connect()
        async with self.lock:
            async with self.conn.execute(sql, parameters) as cursor:
                return await cursor.fetchall()

    async def fetchone(self, sql: str, parameters: tuple = ()):
        await self._connect()
        async with self.lock:
            async with self.conn.execute(sql, parameters) as cursor:
                return await cursor.fetchone()

    async def close(self):
        if self.conn is None:
            return
        async with self.lock:
            if self.conn is None:
                return
            conn, self.conn = self.conn, None
            await conn.execute("PRAGMA optimize;")
            await conn.close()

    @classmethod
    async def close_all(cls):
        await asyncio.gather(*(db.close() for db in cls._instances.values()))
