"""Durable investigation cases backed by the canonical SQLite store."""
from __future__ import annotations

import time
import uuid


class CaseService:
    """Persist bounded case records, entity links, timeline entries and reports."""

    MAX_ROWS = 200
    MAX_TEXT = 4000
    STATUSES = frozenset({"OPEN", "CLOSED"})

    def __init__(self, intelgraph):
        self.intelgraph = intelgraph
        self.storage = intelgraph.storage
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        await self.intelgraph.start()
        statements = (
            "CREATE TABLE IF NOT EXISTS cases (case_id TEXT PRIMARY KEY, title TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'OPEN', summary TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL, updated_at REAL NOT NULL, closed_at REAL)",
            "CREATE TABLE IF NOT EXISTS case_entities (case_id TEXT NOT NULL, entity_id TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'SUBJECT', note TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL, PRIMARY KEY(case_id, entity_id), FOREIGN KEY(case_id) REFERENCES cases(case_id))",
            "CREATE TABLE IF NOT EXISTS case_timeline (id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL, event_at REAL NOT NULL, kind TEXT NOT NULL, description TEXT NOT NULL, entity_id TEXT, observation_id TEXT, created_at REAL NOT NULL, FOREIGN KEY(case_id) REFERENCES cases(case_id))",
            "CREATE INDEX IF NOT EXISTS idx_case_timeline ON case_timeline(case_id,event_at,id)",
            "CREATE INDEX IF NOT EXISTS idx_case_entities ON case_entities(case_id,created_at)",
        )
        for statement in statements:
            await self.storage.execute(statement)
        self._started = True

    async def close(self) -> None:
        self._started = False

    @staticmethod
    def _clean(value: str, limit: int) -> str:
        return str(value or "").strip()[:limit]

    async def create(self, title: str, summary: str = "") -> str:
        if not self._started:
            await self.start()
        title = self._clean(title, 200)
        summary = self._clean(summary, self.MAX_TEXT)
        if not title:
            raise ValueError("Case title is required")
        case_id = uuid.uuid4().hex
        now = time.time()
        await self.storage.execute("INSERT INTO cases(case_id,title,status,summary,created_at,updated_at) VALUES(?,?,?,?,?,?)", (case_id, title, "OPEN", summary, now, now))
        await self.add_timeline(case_id, "CASE_CREATED", title)
        return case_id

    async def get(self, case_id: str) -> dict | None:
        row = await self.storage.fetchone("SELECT case_id,title,status,summary,created_at,updated_at,closed_at FROM cases WHERE case_id=?", (case_id.strip(),))
        return dict(row) if row else None

    async def list(self, *, limit: int = 25) -> list[dict]:
        bounded = max(1, min(int(limit), self.MAX_ROWS))
        rows = await self.storage.fetchall("SELECT case_id,title,status,summary,created_at,updated_at,closed_at FROM cases ORDER BY updated_at DESC LIMIT ?", (bounded,))
        return [dict(row) for row in rows]

    async def add_entity(self, case_id: str, entity_id: str, *, role: str = "SUBJECT", note: str = "") -> None:
        if not await self.get(case_id):
            raise ValueError("Case not found")
        role = self._clean(role.upper(), 32) or "SUBJECT"
        note = self._clean(note, 500)
        if await self.storage.fetchone("SELECT entity_id FROM intel_entities WHERE entity_id=?", (entity_id,)) is None:
            raise ValueError("IntelGraph entity not found")
        now = time.time()
        await self.storage.execute("INSERT OR REPLACE INTO case_entities(case_id,entity_id,role,note,created_at) VALUES(?,?,?,?,?)", (case_id, entity_id, role, note, now))
        await self.storage.execute("UPDATE cases SET updated_at=? WHERE case_id=?", (now, case_id))
        await self.add_timeline(case_id, "ENTITY_ATTACHED", f"Attached entity {entity_id}", entity_id=entity_id)

    async def add_timeline(self, case_id: str, kind: str, description: str, *, entity_id: str | None = None, observation_id: str | None = None, event_at: float | None = None) -> int:
        if not await self.get(case_id):
            raise ValueError("Case not found")
        now = time.time()
        cursor = await self.storage.execute("INSERT INTO case_timeline(case_id,event_at,kind,description,entity_id,observation_id,created_at) VALUES(?,?,?,?,?,?,?)", (case_id, event_at if event_at is not None else now, self._clean(kind.upper(), 64), self._clean(description, self.MAX_TEXT), entity_id, observation_id, now))
        await self.storage.execute("UPDATE cases SET updated_at=? WHERE case_id=?", (now, case_id))
        return int(cursor.lastrowid)

    async def timeline(self, case_id: str, *, limit: int = 100) -> list[dict]:
        bounded = max(1, min(int(limit), self.MAX_ROWS))
        rows = await self.storage.fetchall("SELECT id,event_at,kind,description,entity_id,observation_id FROM case_timeline WHERE case_id=? ORDER BY event_at,id LIMIT ?", (case_id, bounded))
        return [dict(row) for row in rows]

    async def entities(self, case_id: str, *, limit: int = 100) -> list[dict]:
        bounded = max(1, min(int(limit), self.MAX_ROWS))
        rows = await self.storage.fetchall("SELECT ce.entity_id,ce.role,ce.note,e.entity_type,e.canonical_value,e.display_value FROM case_entities ce JOIN intel_entities e ON e.entity_id=ce.entity_id WHERE ce.case_id=? ORDER BY ce.created_at LIMIT ?", (case_id, bounded))
        return [dict(row) for row in rows]

    async def close_case(self, case_id: str) -> None:
        if not await self.get(case_id):
            raise ValueError("Case not found")
        now = time.time()
        await self.storage.execute("UPDATE cases SET status='CLOSED',closed_at=?,updated_at=? WHERE case_id=?", (now, now, case_id))
        await self.add_timeline(case_id, "CASE_CLOSED", "Case closed")

    async def report(self, case_id: str) -> str:
        case = await self.get(case_id)
        if not case:
            raise ValueError("Case not found")
        entities = await self.entities(case_id)
        timeline = await self.timeline(case_id)
        lines = [f"CASE {case['case_id']}", f"Title: {case['title']}", f"Status: {case['status']}", f"Summary: {case['summary'] or '—'}", "", "ENTITIES"]
        lines.extend(f"- {item['role']}: {item['entity_type']} {item['display_value'] or item['canonical_value']}" for item in entities)
        lines.extend(["", "TIMELINE"])
        lines.extend(f"- {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(item['event_at']))} [{item['kind']}] {item['description']}" for item in timeline)
        return "\n".join(lines)[:16_000]
