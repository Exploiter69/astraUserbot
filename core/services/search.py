from __future__ import annotations

import base64
import hashlib
import json
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from core.services.storage import StorageService


@dataclass(frozen=True, slots=True)
class SearchResult:
    source: str
    ref: str
    title: str
    snippet: str
    rank: float
    result_id: str = ""
    evidence_ref: str | None = None


@dataclass(frozen=True, slots=True)
class SearchPage:
    results: list[SearchResult]
    next_cursor: str | None = None


class SearchService:
    """Bounded, rebuildable SQLite FTS5 search over platform and local knowledge."""

    MAX_QUERY = 256
    MAX_RESULTS = 50
    MAX_DOCUMENT_BYTES = 512 * 1024
    TEXT_SUFFIXES = {".md", ".txt", ".rst", ".json"}
    CURSOR_VERSION = 1

    def __init__(self, storage: StorageService, project_root: str | Path) -> None:
        self.storage = storage
        self.project_root = Path(project_root).resolve()
        self._ready = False

    async def start(self) -> None:
        if self._ready:
            return
        row = await self.storage.fetchone("SELECT name FROM sqlite_master WHERE type='table' AND name='search_documents'")
        fts = await self.storage.fetchone("SELECT name FROM sqlite_master WHERE type='table' AND name='search_fts'")
        if not row or not fts:
            raise RuntimeError("Search schema migration is not applied")
        self._ready = True

    async def close(self) -> None:
        self._ready = False

    @staticmethod
    def _clean_query(query: str) -> str:
        query = " ".join(str(query).split())[: SearchService.MAX_QUERY]
        terms = re.findall(r"[\w@./:-]+", query, flags=re.UNICODE)
        return " AND ".join(f'"{term.replace(chr(34), "")}"' for term in terms)

    @staticmethod
    def _cursor_signature(query: str, sources: set[str] | None) -> str:
        normalized_sources = sorted(str(item) for item in (sources or set()) if item)
        payload = json.dumps(
            {"query": " ".join(str(query).split()), "sources": normalized_sources},
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    @classmethod
    def _encode_cursor(cls, *, query: str, sources: set[str] | None, rank: float, result_id: str) -> str:
        payload = {
            "v": cls.CURSOR_VERSION,
            "q": cls._cursor_signature(query, sources),
            "r": repr(float(rank)),
            "id": result_id,
        }
        raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    @classmethod
    def _decode_cursor(cls, cursor: str, *, query: str, sources: set[str] | None) -> tuple[float, str]:
        raw = str(cursor).strip()
        if not raw or len(raw) > 256:
            raise ValueError("Invalid search cursor.")
        padding = "=" * (-len(raw) % 4)
        try:
            payload = json.loads(base64.urlsafe_b64decode((raw + padding).encode("ascii")).decode("utf-8"))
            if payload.get("v") != cls.CURSOR_VERSION or payload.get("q") != cls._cursor_signature(query, sources):
                raise ValueError("Search cursor does not match this query/filter set.")
            rank = float(payload["r"])
            result_id = str(payload["id"])
        except (ValueError, KeyError, TypeError, json.JSONDecodeError, UnicodeError) as exc:
            raise ValueError("Invalid search cursor.") from exc
        if not result_id or len(result_id) > 512:
            raise ValueError("Invalid search cursor.")
        return rank, result_id

    async def upsert(self, *, source: str, ref: str, title: str, content: str) -> None:
        if not self._ready:
            raise RuntimeError("SearchService is not started")
        content = str(content)[: self.MAX_DOCUMENT_BYTES]
        doc_id = f"{source}:{ref}"
        now = time.time()
        await self.storage.transaction([
            ("INSERT INTO search_documents(id,source,ref,title,content,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET source=excluded.source,ref=excluded.ref,title=excluded.title,content=excluded.content,updated_at=excluded.updated_at", (doc_id, source, ref, title[:500], content, now)),
            ("DELETE FROM search_fts WHERE id=?", (doc_id,)),
            ("INSERT INTO search_fts(id,title,content) VALUES(?,?,?)", (doc_id, title[:500], content)),
        ])

    async def remove_source(self, source: str) -> None:
        rows = await self.storage.fetchall("SELECT id FROM search_documents WHERE source=?", (source,))
        statements = [("DELETE FROM search_documents WHERE source=?", (source,))]
        statements.extend(("DELETE FROM search_fts WHERE id=?", (row[0],)) for row in rows)
        await self.storage.transaction(statements)

    async def rebuild(self) -> dict[str, int]:
        if not self._ready:
            raise RuntimeError("SearchService is not started")
        counts: dict[str, int] = {}
        for source in (
            "plugin", "command", "document", "message", "archive_message",
            "intel_entity", "intel_observation", "ocr", "transcript", "case", "media", "security",
        ):
            await self.remove_source(source)
            counts[source] = 0

        rows = await self.storage.fetchall("SELECT name,module,state,updated_at FROM plugins ORDER BY name")
        for row in rows:
            await self.upsert(source="plugin", ref=row[0], title=row[0], content=f"{row[0]} {row[1]} {row[2]}")
            counts["plugin"] += 1
        try:
            from core.registry import registry_snapshot
            for item in registry_snapshot():
                ref = str(item["registration_id"])
                content = " ".join([
                    *item["names"], item["category"], item["description"],
                    item["permission"], item["operation_class"], item["plugin"] or "",
                    *item["examples"],
                ])
                await self.upsert(source="command", ref=ref, title=item["names"][0] if item["names"] else ref, content=content)
                counts["command"] += 1
        except Exception:
            rows = await self.storage.fetchall("SELECT pattern,plugin_name,metadata_json FROM commands ORDER BY pattern")
            for row in rows:
                await self.upsert(source="command", ref=row[0], title=row[0], content=f"{row[1] or ''} {row[2] or ''}")
                counts["command"] += 1

        for path in self.project_root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in self.TEXT_SUFFIXES:
                continue
            if any(part in {".git", "venv", "__pycache__"} for part in path.parts):
                continue
            try:
                if path.stat().st_size > self.MAX_DOCUMENT_BYTES:
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            await self.upsert(source="document", ref=str(path.relative_to(self.project_root)), title=path.name, content=text)
            counts["document"] += 1

        for db_path in (self.project_root / "data" / "databases").glob("*.db"):
            try:
                conn = sqlite3.connect(db_path)
                try:
                    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='message_cache'").fetchone()
                    if not exists:
                        continue
                    for message_id, sender_id, text in conn.execute("SELECT message_id,sender_id,COALESCE(text,'') FROM message_cache ORDER BY created_at DESC LIMIT 5000"):
                        await self.upsert(source="message", ref=f"{db_path.name}:{message_id}", title=f"message {message_id}", content=f"sender {sender_id} {text}")
                        counts["message"] += 1
                finally:
                    conn.close()
            except sqlite3.Error:
                continue

        optional_queries = [
            ("intel_entity", "SELECT entity_id, entity_type, canonical_value, COALESCE(display_value,'') FROM intel_entities ORDER BY updated_at DESC LIMIT 10000"),
            ("intel_observation", "SELECT o.observation_id, o.source_family, COALESCE(o.source_dataset,''), COALESCE(o.matched_field,''), o.evidence_state, COALESCE(e.canonical_value,''), COALESCE(e.display_value,'') FROM intel_observations o LEFT JOIN intel_entities e ON e.entity_id=o.entity_id ORDER BY o.retrieved_at DESC LIMIT 10000"),
            ("ocr", "SELECT o.observation_id, COALESCE(e.canonical_value,''), COALESCE(e.display_value,''), COALESCE(o.provenance_json,'') FROM intel_observations o LEFT JOIN intel_entities e ON e.entity_id=o.entity_id WHERE lower(COALESCE(o.matched_field,''))='ocr_text' ORDER BY o.retrieved_at DESC LIMIT 5000"),
            ("transcript", "SELECT o.observation_id, COALESCE(e.canonical_value,''), COALESCE(e.display_value,''), COALESCE(o.provenance_json,'') FROM intel_observations o LEFT JOIN intel_entities e ON e.entity_id=o.entity_id WHERE lower(COALESCE(o.matched_field,''))='transcript' ORDER BY o.retrieved_at DESC LIMIT 5000"),
            ("media", "SELECT o.observation_id, o.source_family, COALESCE(o.source_dataset,''), COALESCE(o.matched_field,''), o.evidence_state, COALESCE(e.canonical_value,'') FROM intel_observations o LEFT JOIN intel_entities e ON e.entity_id=o.entity_id WHERE lower(o.source_family) LIKE '%media%' ORDER BY o.retrieved_at DESC LIMIT 5000"),
            ("security", "SELECT o.observation_id, o.source_family, COALESCE(o.source_dataset,''), COALESCE(o.matched_field,''), o.evidence_state, COALESCE(e.canonical_value,'') FROM intel_observations o LEFT JOIN intel_entities e ON e.entity_id=o.entity_id WHERE lower(o.source_family) LIKE '%security%' ORDER BY o.retrieved_at DESC LIMIT 5000"),
            ("case", "SELECT case_id, title, status, summary FROM cases ORDER BY updated_at DESC LIMIT 5000"),
        ]
        for source, sql in optional_queries:
            try:
                rows = await self.storage.fetchall(sql)
            except Exception:
                rows = []
            for row in rows:
                ref = str(row[0])
                title = str(row[2] if source == "intel_entity" else row[1])
                content = " ".join(str(item or "") for item in row)
                await self.upsert(source=source, ref=ref, title=title, content=content)
                counts[source] += 1
        return counts

    async def search_page(
        self,
        query: str,
        *,
        limit: int = 10,
        cursor: str | None = None,
        sources: set[str] | None = None,
    ) -> SearchPage:
        cleaned = self._clean_query(query)
        if not cleaned:
            return SearchPage([])
        limit = max(1, min(int(limit), self.MAX_RESULTS))
        clauses = ["search_fts MATCH ?"]
        params: list[object] = [cleaned]
        if sources:
            ordered = sorted(str(item) for item in sources if item)
            if ordered:
                clauses.append("d.source IN (" + ",".join("?" for _ in ordered) + ")")
                params.extend(ordered)

        cursor_rank: float | None = None
        cursor_id: str | None = None
        if cursor:
            cursor_rank, cursor_id = self._decode_cursor(cursor, query=query, sources=sources)
            clauses.append("(bm25(search_fts) > ? OR (bm25(search_fts) = ? AND d.id > ?))")
            params.extend([cursor_rank, cursor_rank, cursor_id])

        params.append(limit + 1)
        rows = await self.storage.fetchall(
            "SELECT d.source,d.ref,d.title,snippet(search_fts,2,'','', '…', 18),bm25(search_fts),d.id FROM search_fts JOIN search_documents d ON d.id=search_fts.id WHERE "
            + " AND ".join(clauses)
            + " ORDER BY bm25(search_fts), d.id LIMIT ?",
            tuple(params),
        )
        has_next = len(rows) > limit
        rows = rows[:limit]
        results = [
            SearchResult(str(row[0]), str(row[1]), str(row[2]), str(row[3]), float(row[4]), result_id=str(row[5]), evidence_ref=str(row[1]))
            for row in rows
        ]
        next_cursor = None
        if has_next and results:
            last = results[-1]
            next_cursor = self._encode_cursor(query=query, sources=sources, rank=last.rank, result_id=last.result_id)
        return SearchPage(results, next_cursor)

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        offset: int = 0,
        sources: set[str] | None = None,
    ) -> list[SearchResult]:
        """Backward-compatible offset search; new product surfaces should prefer search_page()."""
        cleaned = self._clean_query(query)
        if not cleaned:
            return []
        limit = max(1, min(int(limit), self.MAX_RESULTS))
        offset = max(0, min(int(offset), 10000))
        clauses = ["search_fts MATCH ?"]
        params: list[object] = [cleaned]
        if sources:
            ordered = sorted(str(item) for item in sources if item)
            if ordered:
                clauses.append("d.source IN (" + ",".join("?" for _ in ordered) + ")")
                params.extend(ordered)
        params.extend([limit, offset])
        rows = await self.storage.fetchall(
            "SELECT d.source,d.ref,d.title,snippet(search_fts,2,'','', '…', 18),bm25(search_fts),d.id FROM search_fts JOIN search_documents d ON d.id=search_fts.id WHERE "
            + " AND ".join(clauses)
            + " ORDER BY bm25(search_fts), d.id LIMIT ? OFFSET ?",
            tuple(params),
        )
        return [
            SearchResult(str(row[0]), str(row[1]), str(row[2]), str(row[3]), float(row[4]), result_id=str(row[5]), evidence_ref=str(row[1]))
            for row in rows
        ]
