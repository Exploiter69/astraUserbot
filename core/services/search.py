from __future__ import annotations

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


class SearchService:
    """Bounded, rebuildable SQLite FTS5 search over platform and local knowledge."""

    MAX_QUERY = 256
    MAX_RESULTS = 50
    MAX_DOCUMENT_BYTES = 512 * 1024
    TEXT_SUFFIXES = {".md", ".txt", ".rst", ".json"}

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
        for source in ("plugin", "command", "document", "message", "intel_entity", "intel_observation", "case", "media", "security"):
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
            ("intel_observation", "SELECT observation_id, source_family, COALESCE(source_dataset,''), COALESCE(matched_field,''), evidence_state FROM intel_observations ORDER BY retrieved_at DESC LIMIT 10000"),
            ("media", "SELECT observation_id, source_family, COALESCE(source_dataset,''), COALESCE(matched_field,''), evidence_state FROM intel_observations WHERE lower(source_family) LIKE '%media%' ORDER BY retrieved_at DESC LIMIT 5000"),
            ("security", "SELECT observation_id, source_family, COALESCE(source_dataset,''), COALESCE(matched_field,''), evidence_state FROM intel_observations WHERE lower(source_family) LIKE '%security%' ORDER BY retrieved_at DESC LIMIT 5000"),
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

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        offset: int = 0,
        sources: set[str] | None = None,
    ) -> list[SearchResult]:
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

        return [SearchResult(str(row[0]), str(row[1]), str(row[2]), str(row[3]), float(row[4])) for row in rows]
