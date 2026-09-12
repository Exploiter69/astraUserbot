"""Read-only audit for AstraUserbot SQLite storage contracts."""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "plugins"


def _python_files() -> list[Path]:
    return sorted(ROOT.rglob("*.py"))


def plugin_database_inventory() -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for path in sorted(PLUGIN_ROOT.rglob("*.py")):
        if path.name == "__init__.py" or path.name.startswith("_"):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        names: set[str] = set()
        schemas = 0
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Attribute) and node.func.attr == "get":
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "Database":
                    if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                        names.add(node.args[0].value)
            if isinstance(node.func, ast.Attribute) and node.func.attr == "init_schema":
                schemas += 1
        for name in sorted(names):
            records.append({
                "database": name,
                "plugin": str(path.relative_to(ROOT)),
                "schema_initializers": schemas,
            })
    return records


def migration_audit() -> dict[str, object]:
    source = (ROOT / "core/services/storage.py").read_text(encoding="utf-8")
    checks = {
        "numbered_migrations": "MIGRATIONS:" in source and "tuple[tuple[int, str]" in source,
        "migration_checksum": "hashlib.sha256" in source and "Migration checksum mismatch" in source,
        "migration_lock": "BEGIN IMMEDIATE" in source,
        "migration_rollback": "await self.conn.rollback()" in source,
        "foreign_keys": "PRAGMA foreign_keys=ON" in source,
        "wal": "PRAGMA journal_mode=WAL" in source,
        "busy_timeout": "PRAGMA busy_timeout=" in source,
        "integrity_check": "PRAGMA integrity_check" in source,
        "database_size_observable": "async def database_size" in source,
    }
    return checks


def transaction_audit() -> dict[str, object]:
    storage = (ROOT / "core/services/storage.py").read_text(encoding="utf-8")
    database = (ROOT / "core/database.py").read_text(encoding="utf-8")
    return {
        "platform_transaction_api": "async def transaction(" in storage,
        "platform_transaction_rollback": "Database transaction failed" in storage and "await self.conn.rollback()" in storage,
        "plugin_transaction_api": "async def transaction(" in database,
        "plugin_transaction_rollback": "Database transaction failed" in database and "await self.conn.rollback()" in database,
        "plugin_database_size": "async def database_size" in database,
    }


def backup_audit() -> dict[str, object]:
    storage = (ROOT / "core/services/storage.py").read_text(encoding="utf-8")
    database = (ROOT / "core/database.py").read_text(encoding="utf-8")
    return {
        "platform_sqlite_backup": "self.conn.backup(target_conn)" in storage,
        "platform_backup_integrity": "Backup integrity check failed" in storage,
        "platform_atomic_publish": "os.replace(temp_path, target)" in storage,
        "platform_restore": "async def restore(" in storage,
        "restore_integrity_gate": "Refusing restore from an integrity-failed backup" in storage,
        "plugin_sqlite_backup": "self.conn.backup(target_conn)" in database,
        "plugin_backup_integrity": "Backup integrity check failed" in database,
        "plugin_atomic_publish": "os.replace(temp, target)" in database,
    }


def search_audit() -> dict[str, object]:
    search = (ROOT / "core/services/search.py").read_text(encoding="utf-8")
    storage = (ROOT / "core/services/storage.py").read_text(encoding="utf-8")
    return {
        "fts5": "CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5" in storage,
        "transactional_upsert": "await self.storage.transaction" in search,
        "rebuildable": "async def rebuild" in search and "await self.remove_source" in search,
        "consistency_check": "async def fts_consistency" in storage,
        "bounded_query": "MAX_QUERY" in search and "MAX_RESULTS" in search,
        "bounded_document": "MAX_DOCUMENT_BYTES" in search,
    }


def retention_audit() -> dict[str, object]:
    jobs = (ROOT / "core/services/jobs.py").read_text(encoding="utf-8")
    database = (ROOT / "core/database.py").read_text(encoding="utf-8")
    return {
        "job_retention": "TERMINAL_RETENTION_SECONDS" in jobs and "async def cleanup" in jobs,
        "uncertain_preserved": "JobState.UNCERTAIN" in jobs and "UNCERTAIN" in jobs,
        "lease_aware_cleanup": "leases" in jobs and "DELETE FROM jobs" in jobs,
        "plugin_database_size_bound": "MAX_BACKUP_BYTES" in database,
    }


def main() -> int:
    migrations = migration_audit()
    transactions = transaction_audit()
    backups = backup_audit()
    search = search_audit()
    retention = retention_audit()
    inventory = plugin_database_inventory()
    report = {
        "phase": 4,
        "purpose": "storage and database correctness",
        "read_only": True,
        "migrations": migrations,
        "transactions": transactions,
        "backup_restore": backups,
        "fts": search,
        "retention": retention,
        "plugin_database_inventory": inventory,
        "plugin_database_count": len({item["database"] for item in inventory}),
    }
    print("=== STORAGE / DATABASE HARDENING AUDIT ===")
    print(json.dumps(report, indent=2, sort_keys=True))
    checks = {**migrations, **transactions, **backups, **search, **retention}
    failures = [name for name, ok in checks.items() if not ok]
    if failures:
        print("STORAGE_HARDENING_AUDIT_FAIL")
        print("FAILURES:", ", ".join(failures))
        return 1
    print("STORAGE_HARDENING_AUDIT_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
