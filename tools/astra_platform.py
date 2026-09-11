from __future__ import annotations

import argparse
import asyncio
import compileall
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.services.search import SearchService
from core.services.storage import StorageService


async def migrate() -> int:
    service = StorageService(ROOT)
    await service.start()
    ok = await service.integrity_check()
    await service.close()
    print(json.dumps({"storage_integrity": ok}))
    return 0 if ok else 1


async def backup(destination: str) -> int:
    service = StorageService(ROOT)
    await service.start()
    target = Path(destination).expanduser().resolve()
    await service.backup(target)
    await service.close()
    print(target)
    return 0


async def selftest() -> int:
    ok_compile = compileall.compile_dir(str(ROOT), quiet=1, maxlevels=20)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        storage = StorageService(root)
        await storage.start()
        search = SearchService(storage, root)
        await search.start()
        await search.upsert(source="selftest", ref="fixture", title="fixture", content="astra platform selftest")
        found = bool(await search.search("selftest"))
        integrity = await storage.integrity_check()
        await search.close()
        await storage.close()
    result = {"compile": ok_compile, "search": found, "storage_integrity": integrity}
    print(json.dumps(result, indent=2))
    return 0 if all(result.values()) else 1


def benchmark() -> int:
    loops = 1000
    started = time.perf_counter()
    for _ in range(loops):
        _ = json.dumps({"operation": "benchmark", "value": 1}, separators=(",", ":"))
    elapsed = time.perf_counter() - started
    print(json.dumps({"operation": "json_serialization", "iterations": loops, "elapsed_ms": elapsed * 1000, "ops_per_second": loops / elapsed}))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="AstraUserbot platform maintenance tools")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate")
    sub.add_parser("selftest")
    sub.add_parser("benchmark")
    backup_parser = sub.add_parser("backup")
    backup_parser.add_argument("destination")
    args = parser.parse_args()
    if args.command == "migrate":
        return asyncio.run(migrate())
    if args.command == "selftest":
        return asyncio.run(selftest())
    if args.command == "backup":
        return asyncio.run(backup(args.destination))
    return benchmark()


if __name__ == "__main__":
    raise SystemExit(main())
