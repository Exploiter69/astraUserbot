import asyncio
import sqlite3
import tempfile
import unittest
from pathlib import Path

from core.database import Database, DatabaseError
from core.services.search import SearchService
from core.services.storage import StorageError, StorageService


class StorageHardeningTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.storage = StorageService(self.root)
        await self.storage.start()

    async def asyncTearDown(self):
        await self.storage.close()
        self.tmp.cleanup()

    async def test_migrations_are_serialized_across_concurrent_openers(self):
        first = StorageService(self.root)
        second = StorageService(self.root)
        await self.storage.close()
        await asyncio.gather(first.start(), second.start())
        self.assertEqual([row[0] for row in await first.fetchall("SELECT version FROM schema_migrations ORDER BY version")], [1, 2, 3, 4, 5, 6, 7])
        await first.close()
        await second.close()
        self.storage = StorageService(self.root)
        await self.storage.start()

    async def test_transaction_rolls_back_all_statements(self):
        await self.storage.execute("INSERT INTO audit_events(kind,subject_id,payload_json,created_at) VALUES(?,?,?,?)", ("before", "x", "{}", 1))
        with self.assertRaises(StorageError):
            await self.storage.transaction([("INSERT INTO audit_events(kind,subject_id,payload_json,created_at) VALUES(?,?,?,?)", ("atomic", "x", "{}", 2)), ("INSERT INTO missing_table(value) VALUES(?)", ("boom",))])
        row = await self.storage.fetchone("SELECT COUNT(*) FROM audit_events WHERE kind='atomic'")
        self.assertEqual(row[0], 0)

    async def test_concurrent_writers_preserve_all_rows(self):
        async def write(index: int):
            await self.storage.execute("INSERT INTO audit_events(kind,subject_id,payload_json,created_at) VALUES(?,?,?,?)", ("concurrent", str(index), "{}", float(index)))
        await asyncio.gather(*(write(index) for index in range(50)))
        row = await self.storage.fetchone("SELECT COUNT(*) FROM audit_events WHERE kind='concurrent'")
        self.assertEqual(row[0], 50)

    async def test_wal_and_foreign_keys_are_enabled(self):
        self.assertEqual((await self.storage.fetchone("PRAGMA journal_mode"))[0].lower(), "wal")
        self.assertEqual((await self.storage.fetchone("PRAGMA foreign_keys"))[0], 1)
        self.assertEqual((await self.storage.fetchone("PRAGMA busy_timeout"))[0], 5000)

    async def test_foreign_key_violations_are_rejected(self):
        with self.assertRaises(StorageError):
            await self.storage.execute("INSERT INTO commands(pattern,plugin_name,aliases_json,metadata_json,updated_at) VALUES(?,?,?,?,?)", ("broken", "missing-plugin", "[]", "{}", 1))

    async def test_fts_upsert_and_consistency(self):
        (self.root / "README.md").write_text("durable storage", encoding="utf-8")
        search = SearchService(self.storage, self.root)
        await search.start()
        await search.upsert(source="document", ref="one", title="SQLite", content="durable storage")
        result = await search.search("durable")
        self.assertEqual(len(result), 1)
        self.assertTrue((await self.storage.fts_consistency())["consistent"])
        await self.storage.execute("DELETE FROM search_fts WHERE id=?", ("document:one",))
        self.assertFalse((await self.storage.fts_consistency())["consistent"])
        counts = await search.rebuild()
        self.assertGreaterEqual(counts["document"], 1)
        self.assertTrue((await self.storage.fts_consistency())["consistent"])
        self.assertEqual(len(await search.search("durable")), 1)
        await search.close()

    async def test_verified_backup_and_restore_round_trip(self):
        await self.storage.execute("INSERT INTO audit_events(kind,subject_id,payload_json,created_at) VALUES(?,?,?,?)", ("backup-test", "restore", "{\"ok\":true}", 123))
        backup = self.root / "verified-backup.db"
        await self.storage.backup(backup)
        conn = sqlite3.connect(backup)
        try:
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM audit_events WHERE kind='backup-test'").fetchone()[0], 1)
        finally:
            conn.close()
        await self.storage.close()
        restored = StorageService(self.root / "restored")
        await restored.restore(backup)
        await restored.start()
        self.assertTrue(await restored.integrity_check())
        self.assertEqual((await restored.fetchone("SELECT COUNT(*) FROM audit_events WHERE kind='backup-test'"))[0], 1)
        await restored.close()
        self.storage = StorageService(self.root)
        await self.storage.start()

    async def test_restore_refuses_corrupt_backup(self):
        corrupt = self.root / "corrupt.db"
        corrupt.write_bytes(b"not-a-sqlite-database")
        with self.assertRaises(StorageError):
            await self.storage.restore(corrupt)

    async def test_corruption_is_reported_as_storage_error(self):
        await self.storage.close()
        db_path = self.root / "data" / "databases" / "platform.db"
        with db_path.open("r+b") as handle:
            handle.write(b"NOTSQLITE")
        broken = StorageService(self.root)
        with self.assertRaises(StorageError):
            await broken.start()
        await broken.close()
        self.storage = StorageService(self.root)
        clean = StorageService(self.root / "clean")
        await clean.start()
        clean_backup = self.root / "clean.db"
        await clean.backup(clean_backup)
        await clean.close()
        await self.storage.restore(clean_backup)
        await self.storage.start()


class LegacyPluginDatabaseHardeningTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.name = f"storage_hardening_{id(self)}"
        self.db = Database.get(self.name)
        await self.db.init_schema("CREATE TABLE IF NOT EXISTS values_table (id INTEGER PRIMARY KEY, value TEXT NOT NULL);")

    async def asyncTearDown(self):
        await self.db.close()
        Database._instances.pop(self.name, None)
        try:
            self.db.path.unlink()
        except FileNotFoundError:
            pass
        for suffix in ("-wal", "-shm"):
            try:
                Path(str(self.db.path) + suffix).unlink()
            except FileNotFoundError:
                pass

    async def test_plugin_database_wal_integrity_transaction_and_backup(self):
        self.assertEqual((await self.db.fetchone("PRAGMA journal_mode"))[0].lower(), "wal")
        self.assertTrue(await self.db.integrity_check())
        with self.assertRaises(DatabaseError):
            await self.db.transaction([("INSERT INTO values_table(id,value) VALUES(?,?)", (1, "ok")), ("INSERT INTO missing_table(value) VALUES(?)", ("boom",))])
        self.assertEqual((await self.db.fetchone("SELECT COUNT(*) FROM values_table"))[0], 0)
        await self.db.execute("INSERT INTO values_table(id,value) VALUES(?,?)", (1, "ok"))
        backup = self.db.path.parent / f"{self.name}.backup.db"
        await self.db.backup(backup)
        self.assertTrue(backup.exists())
        conn = sqlite3.connect(backup)
        try:
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(conn.execute("SELECT value FROM values_table").fetchone()[0], "ok")
        finally:
            conn.close()
        backup.unlink()

    async def test_plugin_database_name_is_bounded(self):
        with self.assertRaises(DatabaseError):
            Database.get("../escape")
