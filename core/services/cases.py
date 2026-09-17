"""Durable investigation cases backed by the canonical SQLite store."""
from __future__ import annotations

import json
import time
import uuid


class CaseService:
    """Persist bounded case records, entity links, evidence-aware timelines and reports."""

    MAX_ROWS = 200
    MAX_TEXT = 4000
    MAX_OBSERVATIONS = 100
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
            "CREATE TABLE IF NOT EXISTS case_observations (case_id TEXT NOT NULL, observation_id TEXT NOT NULL, created_at REAL NOT NULL, PRIMARY KEY(case_id, observation_id), FOREIGN KEY(case_id) REFERENCES cases(case_id))",
            "CREATE TABLE IF NOT EXISTS case_notes (id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL, note TEXT NOT NULL, created_at REAL NOT NULL, FOREIGN KEY(case_id) REFERENCES cases(case_id))",
            "CREATE TABLE IF NOT EXISTS case_sources (case_id TEXT NOT NULL, source_id TEXT NOT NULL, created_at REAL NOT NULL, PRIMARY KEY(case_id, source_id), FOREIGN KEY(case_id) REFERENCES cases(case_id))",
            "CREATE TABLE IF NOT EXISTS case_events (id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL, event_at REAL NOT NULL, kind TEXT NOT NULL, description TEXT NOT NULL, created_at REAL NOT NULL, FOREIGN KEY(case_id) REFERENCES cases(case_id))",
            "CREATE INDEX IF NOT EXISTS idx_case_timeline ON case_timeline(case_id,event_at,id)",
            "CREATE INDEX IF NOT EXISTS idx_case_entities ON case_entities(case_id,created_at)",
            "CREATE INDEX IF NOT EXISTS idx_case_observations ON case_observations(case_id,created_at)",
            "CREATE INDEX IF NOT EXISTS idx_case_events ON case_events(case_id,event_at,id)",
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
        observations = await self.storage.fetchall("SELECT observation_id,source_id FROM intel_observations WHERE entity_id=? ORDER BY COALESCE(observed_at,retrieved_at) DESC LIMIT ?", (entity_id, self.MAX_OBSERVATIONS))
        for observation in observations:
            await self.storage.execute("INSERT OR IGNORE INTO case_observations(case_id,observation_id,created_at) VALUES(?,?,?)", (case_id, observation["observation_id"], now))
            await self.storage.execute("INSERT OR IGNORE INTO case_sources(case_id,source_id,created_at) VALUES(?,?,?)", (case_id, observation["source_id"], now))
        await self.add_timeline(case_id, "ENTITY_ATTACHED", f"Attached entity {entity_id}", entity_id=entity_id)

    async def add_timeline(self, case_id: str, kind: str, description: str, *, entity_id: str | None = None, observation_id: str | None = None, event_at: float | None = None) -> int:
        if not await self.get(case_id):
            raise ValueError("Case not found")
        now = time.time()
        event_time = event_at if event_at is not None else now
        cursor = await self.storage.execute("INSERT INTO case_timeline(case_id,event_at,kind,description,entity_id,observation_id,created_at) VALUES(?,?,?,?,?,?,?)", (case_id, event_time, self._clean(kind.upper(), 64), self._clean(description, self.MAX_TEXT), entity_id, observation_id, now))
        await self.storage.execute("UPDATE cases SET updated_at=? WHERE case_id=?", (now, case_id))
        await self.storage.execute("INSERT INTO case_events(case_id,event_at,kind,description,created_at) VALUES(?,?,?,?,?)", (case_id, event_time, self._clean(kind.upper(), 64), self._clean(description, self.MAX_TEXT), now))
        if observation_id:
            await self.storage.execute("INSERT OR IGNORE INTO case_observations(case_id,observation_id,created_at) VALUES(?,?,?)", (case_id, observation_id, now))
        return int(cursor.lastrowid)

    async def timeline(self, case_id: str, *, limit: int = 100) -> list[dict]:
        bounded = max(1, min(int(limit), self.MAX_ROWS))
        rows = await self.storage.fetchall("SELECT id,event_at,kind,description,entity_id,observation_id FROM case_timeline WHERE case_id=? ORDER BY event_at,id LIMIT ?", (case_id, bounded))
        return [dict(row) for row in rows]

    async def entities(self, case_id: str, *, limit: int = 100) -> list[dict]:
        bounded = max(1, min(int(limit), self.MAX_ROWS))
        rows = await self.storage.fetchall("SELECT ce.entity_id,ce.role,ce.note,e.entity_type,e.canonical_value,e.display_value FROM case_entities ce JOIN intel_entities e ON e.entity_id=ce.entity_id WHERE ce.case_id=? ORDER BY ce.created_at LIMIT ?", (case_id, bounded))
        return [dict(row) for row in rows]

    async def observations(self, case_id: str, *, limit: int = 100) -> list[dict]:
        bounded = max(1, min(int(limit), self.MAX_OBSERVATIONS))
        rows = await self.storage.fetchall(
            """SELECT o.observation_id,o.entity_id,o.source_id,o.source_family,o.evidence_state,o.confidence,
                      COALESCE(o.observed_at,o.retrieved_at) AS observed_at,o.provenance_json,
                      e.entity_type,e.canonical_value,e.display_value
               FROM case_observations co JOIN intel_observations o ON o.observation_id=co.observation_id
               JOIN intel_entities e ON e.entity_id=o.entity_id
               WHERE co.case_id=? ORDER BY COALESCE(o.observed_at,o.retrieved_at),o.observation_id LIMIT ?""",
            (case_id, bounded),
        )
        result = []
        for row in rows:
            item = dict(row)
            try:
                item["provenance"] = json.loads(item.pop("provenance_json") or "{}")
            except (TypeError, ValueError):
                item["provenance"] = {}
            result.append(item)
        return result

    async def sources(self, case_id: str, *, limit: int = 100) -> list[str]:
        bounded = max(1, min(int(limit), self.MAX_ROWS))
        rows = await self.storage.fetchall("SELECT source_id FROM case_sources WHERE case_id=? ORDER BY source_id LIMIT ?", (case_id, bounded))
        return [str(row["source_id"]) for row in rows]

    async def add_note(self, case_id: str, note: str) -> None:
        if not await self.get(case_id):
            raise ValueError("Case not found")
        now = time.time()
        await self.storage.execute("INSERT INTO case_notes(case_id,note,created_at) VALUES(?,?,?)", (case_id, self._clean(note, self.MAX_TEXT), now))
        await self.storage.execute("UPDATE cases SET updated_at=? WHERE case_id=?", (now, case_id))

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
        observations = await self.observations(case_id)
        sources = await self.sources(case_id)
        notes = await self.storage.fetchall("SELECT note,created_at FROM case_notes WHERE case_id=? ORDER BY created_at LIMIT ?", (case_id, self.MAX_ROWS))
        lines = [f"CASE {case['case_id']}", f"Title: {case['title']}", f"Status: {case['status']}", f"Summary: {case['summary'] or '—'}", "", "VERIFIED / DERIVED OBSERVATIONS"]
        if observations:
            for item in observations:
                lines.append(f"- {item['evidence_state']} · confidence={float(item['confidence']):.2f} · {item['entity_type']} {item['display_value'] or item['canonical_value']} · source={item['source_id']} · {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(item['observed_at']))}")
        else:
            lines.append("- No linked observations.")
        lines.extend(["", "ENTITIES"])
        lines.extend(f"- {item['role']}: {item['entity_type']} {item['display_value'] or item['canonical_value']}" for item in entities)
        lines.extend(["", "SOURCES"])
        lines.extend(f"- {source}" for source in sources)
        lines.extend(["", "NOTES"])
        lines.extend(f"- {item['note']}" for item in notes)
        lines.extend(["", "TIMELINE"])
        lines.extend(f"- {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(item['event_at']))} [{item['kind']}] {item['description']}" for item in timeline)
        return "\n".join(lines)[:16_000]
