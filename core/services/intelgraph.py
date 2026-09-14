"""Evidence-first local IntelGraph substrate backed by the canonical SQLite store."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Any

from core.services.storage import StorageService


EVIDENCE_STATES = {"OBSERVED", "DERIVED", "CORRELATED", "INFERRED", "UNKNOWN", "CONTRADICTED"}


class IntelGraph:
    """Store canonical entities, sources, observations and explainable relationships."""

    MAX_QUERY_ROWS = 500

    def __init__(self, storage: StorageService) -> None:
        self.storage = storage
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        await self.storage.fetchone("SELECT 1 FROM intel_entities LIMIT 1")
        self._started = True

    async def close(self) -> None:
        self._started = False

    async def add_source(self, *, source_id: str, source_family: str, provider: str, source_type: str,
                         dataset_id: str | None = None, dataset_version: str | None = None,
                         uri: str | None = None, lineage_class: str = "UNKNOWN",
                         lineage_confidence: float = 0.0, metadata: dict[str, Any] | None = None) -> str:
        self._require_started()
        now = time.time()
        await self.storage.execute(
            """INSERT INTO intel_sources(source_id,source_family,provider,dataset_id,dataset_version,source_type,uri,lineage_class,lineage_confidence,metadata_json,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(source_id) DO UPDATE SET source_family=excluded.source_family,provider=excluded.provider,dataset_id=excluded.dataset_id,dataset_version=excluded.dataset_version,source_type=excluded.source_type,uri=excluded.uri,lineage_class=excluded.lineage_class,lineage_confidence=excluded.lineage_confidence,metadata_json=excluded.metadata_json,updated_at=excluded.updated_at""",
            (source_id, source_family, provider, dataset_id, dataset_version, source_type, uri,
             lineage_class, max(0.0, min(1.0, float(lineage_confidence))), json.dumps(metadata or {}, sort_keys=True), now, now),
        )
        return source_id

    async def add_entity(self, *, entity_type: str, canonical_value: str, display_value: str | None = None,
                         entity_id: str | None = None) -> str:
        self._require_started()
        canonical = canonical_value.strip()
        if not canonical:
            raise ValueError("canonical_value must not be empty")
        entity_id = entity_id or hashlib.sha256(f"{entity_type}\0{canonical}".encode()).hexdigest()
        now = time.time()
        await self.storage.execute(
            """INSERT INTO intel_entities(entity_id,entity_type,canonical_value,display_value,created_at,updated_at)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(entity_type,canonical_value) DO UPDATE SET display_value=COALESCE(excluded.display_value,intel_entities.display_value),updated_at=excluded.updated_at""",
            (entity_id, entity_type, canonical, display_value, now, now),
        )
        row = await self.storage.fetchone("SELECT entity_id FROM intel_entities WHERE entity_type=? AND canonical_value=?", (entity_type, canonical))
        return str(row[0])

    async def add_observation(self, *, entity_id: str, source_id: str, source_family: str,
                              source_dataset: str | None = None, source_version: str | None = None,
                              observed_at: float | None = None, query_context: str | None = None,
                              matched_field: str | None = None, match_type: str | None = None,
                              evidence_state: str = "OBSERVED", confidence: float = 0.0,
                              provenance: dict[str, Any] | None = None, observation_id: str | None = None) -> str:
        self._require_started()
        if evidence_state not in EVIDENCE_STATES:
            raise ValueError(f"unsupported evidence_state: {evidence_state}")
        observation_id = observation_id or uuid.uuid4().hex
        await self.storage.execute(
            """INSERT INTO intel_observations(observation_id,entity_id,source_id,source_family,source_dataset,source_version,retrieved_at,observed_at,query_context,matched_field,match_type,evidence_state,confidence,provenance_json)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (observation_id, entity_id, source_id, source_family, source_dataset, source_version,
             time.time(), observed_at, query_context, matched_field, match_type, evidence_state,
             max(0.0, min(1.0, float(confidence))), json.dumps(provenance or {}, sort_keys=True)),
        )
        return observation_id

    async def add_relationship(self, *, from_entity_id: str, relationship_type: str, to_entity_id: str,
                               evidence_state: str = "CORRELATED", confidence: float = 0.0,
                               observation_id: str | None = None, relationship_id: str | None = None) -> str:
        self._require_started()
        if evidence_state not in EVIDENCE_STATES:
            raise ValueError(f"unsupported evidence_state: {evidence_state}")
        relationship_id = relationship_id or uuid.uuid4().hex
        now = time.time()
        await self.storage.execute(
            "INSERT INTO intel_relationships(relationship_id,from_entity_id,relationship_type,to_entity_id,evidence_state,confidence,observation_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (relationship_id, from_entity_id, relationship_type, to_entity_id, evidence_state,
             max(0.0, min(1.0, float(confidence))), observation_id, now, now),
        )
        return relationship_id

    async def neighbors(self, entity_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        self._require_started()
        bounded = max(1, min(int(limit), self.MAX_QUERY_ROWS))
        rows = await self.storage.fetchall(
            """SELECT r.relationship_id,r.relationship_type,r.evidence_state,r.confidence,
                      CASE WHEN r.from_entity_id=? THEN r.to_entity_id ELSE r.from_entity_id END AS related_entity_id
               FROM intel_relationships r
               WHERE r.from_entity_id=? OR r.to_entity_id=?
               ORDER BY r.confidence DESC,r.updated_at DESC LIMIT ?""",
            (entity_id, entity_id, entity_id, bounded),
        )
        return [dict(row) for row in rows]

    async def evidence(self, entity_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        self._require_started()
        bounded = max(1, min(int(limit), self.MAX_QUERY_ROWS))
        rows = await self.storage.fetchall(
            "SELECT * FROM intel_observations WHERE entity_id=? ORDER BY COALESCE(observed_at,retrieved_at) DESC LIMIT ?",
            (entity_id, bounded),
        )
        return [dict(row) for row in rows]

    def _require_started(self) -> None:
        if not self._started:
            raise RuntimeError("IntelGraph is not started")
