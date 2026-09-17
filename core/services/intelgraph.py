"""Evidence-first local IntelGraph substrate backed by the canonical SQLite store."""

from __future__ import annotations

import hashlib
import inspect
import json
import time
import uuid
from typing import Any, Awaitable, Callable

from core.services.ioc import IOC, extract as extract_iocs
from core.services.storage import StorageService


EVIDENCE_STATES = frozenset(
    {"OBSERVED", "DERIVED", "CORRELATED", "INFERRED", "UNKNOWN", "CONTRADICTED"}
)
RELATIONSHIP_TYPES = frozenset(
    {
        "OWNS",
        "USES",
        "RESOLVES_TO",
        "MENTIONS",
        "LINKS_TO",
        "POSTED",
        "SEEN_WITH",
        "SHARES_HASH",
        "SHARES_USERNAME",
        "SHARES_DOMAIN",
    }
)
ObservationSink = Callable[[dict[str, Any]], Awaitable[Any] | Any]


class IntelGraph:
    """Store canonical entities, sources, observations and explainable relationships."""

    MAX_QUERY_ROWS = 500
    MAX_TEXT_BYTES = 64 * 1024

    def __init__(self, storage: StorageService) -> None:
        self.storage = storage
        self._started = False
        self._observation_sinks: list[ObservationSink] = []

    def add_observation_sink(self, sink: ObservationSink) -> None:
        if not callable(sink):
            raise TypeError("observation sink must be callable")
        if sink not in self._observation_sinks:
            self._observation_sinks.append(sink)

    async def start(self) -> None:
        if self._started:
            return
        await self.storage.fetchone("SELECT 1 FROM intel_entities LIMIT 1")
        self._started = True

    async def close(self) -> None:
        self._started = False
        self._observation_sinks.clear()

    async def add_source(
        self,
        *,
        source_id: str,
        source_family: str,
        provider: str,
        source_type: str,
        dataset_id: str | None = None,
        dataset_version: str | None = None,
        uri: str | None = None,
        lineage_class: str = "UNKNOWN",
        lineage_confidence: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        self._require_started()
        source_id = source_id.strip()
        source_family = source_family.strip()
        provider = provider.strip()
        source_type = source_type.strip()
        if not source_id or not source_family or not provider or not source_type:
            raise ValueError("source_id, source_family, provider and source_type are required")
        now = time.time()
        await self.storage.execute(
            """INSERT INTO intel_sources(source_id,source_family,provider,dataset_id,dataset_version,source_type,uri,lineage_class,lineage_confidence,metadata_json,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(source_id) DO UPDATE SET source_family=excluded.source_family,provider=excluded.provider,dataset_id=excluded.dataset_id,dataset_version=excluded.dataset_version,source_type=excluded.source_type,uri=excluded.uri,lineage_class=excluded.lineage_class,lineage_confidence=excluded.lineage_confidence,metadata_json=excluded.metadata_json,updated_at=excluded.updated_at""",
            (
                source_id,
                source_family,
                provider,
                dataset_id,
                dataset_version,
                source_type,
                uri,
                lineage_class,
                max(0.0, min(1.0, float(lineage_confidence))),
                json.dumps(metadata or {}, sort_keys=True),
                now,
                now,
            ),
        )
        return source_id

    async def add_entity(
        self,
        *,
        entity_type: str,
        canonical_value: str,
        display_value: str | None = None,
        entity_id: str | None = None,
    ) -> str:
        self._require_started()
        entity_type = entity_type.strip().upper()
        canonical = canonical_value.strip()
        if not entity_type or not canonical:
            raise ValueError("entity_type and canonical_value must not be empty")
        entity_id = entity_id or hashlib.sha256(f"{entity_type}\0{canonical}".encode()).hexdigest()
        now = time.time()
        await self.storage.execute(
            """INSERT INTO intel_entities(entity_id,entity_type,canonical_value,display_value,created_at,updated_at)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(entity_type,canonical_value) DO UPDATE SET display_value=COALESCE(excluded.display_value,intel_entities.display_value),updated_at=excluded.updated_at""",
            (entity_id, entity_type, canonical, display_value, now, now),
        )
        row = await self.storage.fetchone(
            "SELECT entity_id FROM intel_entities WHERE entity_type=? AND canonical_value=?",
            (entity_type, canonical),
        )
        return str(row[0])

    async def add_observation(
        self,
        *,
        entity_id: str,
        source_id: str,
        source_family: str,
        source_dataset: str | None = None,
        source_version: str | None = None,
        observed_at: float | None = None,
        query_context: str | None = None,
        matched_field: str | None = None,
        match_type: str | None = None,
        evidence_state: str = "OBSERVED",
        confidence: float = 0.0,
        provenance: dict[str, Any] | None = None,
        observation_id: str | None = None,
    ) -> str:
        self._require_started()
        if evidence_state not in EVIDENCE_STATES:
            raise ValueError(f"unsupported evidence_state: {evidence_state}")
        source = await self.storage.fetchone(
            "SELECT source_family FROM intel_sources WHERE source_id=?", (source_id,)
        )
        if source is None:
            raise ValueError(f"unknown source_id: {source_id}")
        if str(source[0]) != source_family:
            raise ValueError("source_family does not match the registered source")
        observation_id = observation_id or uuid.uuid4().hex
        bounded_confidence = max(0.0, min(1.0, float(confidence)))
        await self.storage.execute(
            """INSERT INTO intel_observations(observation_id,entity_id,source_id,source_family,source_dataset,source_version,retrieved_at,observed_at,query_context,matched_field,match_type,evidence_state,confidence,provenance_json)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                observation_id,
                entity_id,
                source_id,
                source_family,
                source_dataset,
                source_version,
                time.time(),
                observed_at,
                query_context,
                matched_field,
                match_type,
                evidence_state,
                bounded_confidence,
                json.dumps(provenance or {}, sort_keys=True),
            ),
        )
        observation = {
            "event_id": f"intel:{observation_id}",
            "event_type": "INTELLIGENCE_OBSERVED",
            "observed_at": observed_at if observed_at is not None else time.time(),
            "source_peer": source_id,
            "message_id": None,
            "entity_id": entity_id,
            "payload": {
                "observation_id": observation_id,
                "intel_entity_id": entity_id,
                "source_id": source_id,
                "source_family": source_family,
                "source_dataset": source_dataset,
                "source_version": source_version,
                "matched_field": matched_field,
                "match_type": match_type,
                "evidence_state": evidence_state,
                "confidence": bounded_confidence,
            },
        }
        for sink in tuple(self._observation_sinks):
            try:
                result = sink(observation)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                # Intelligence persistence must not depend on automation availability.
                continue
        return observation_id

    async def add_relationship(
        self,
        *,
        from_entity_id: str,
        relationship_type: str,
        to_entity_id: str,
        evidence_state: str = "CORRELATED",
        confidence: float = 0.0,
        observation_id: str | None = None,
        relationship_id: str | None = None,
    ) -> str:
        self._require_started()
        relationship_type = relationship_type.strip().upper()
        if relationship_type not in RELATIONSHIP_TYPES:
            raise ValueError(f"unsupported relationship_type: {relationship_type}")
        if evidence_state not in EVIDENCE_STATES:
            raise ValueError(f"unsupported evidence_state: {evidence_state}")
        if from_entity_id == to_entity_id:
            raise ValueError("self relationships are not allowed")
        relationship_id = relationship_id or uuid.uuid4().hex
        now = time.time()
        await self.storage.execute(
            "INSERT INTO intel_relationships(relationship_id,from_entity_id,relationship_type,to_entity_id,evidence_state,confidence,observation_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                relationship_id,
                from_entity_id,
                relationship_type,
                to_entity_id,
                evidence_state,
                max(0.0, min(1.0, float(confidence))),
                observation_id,
                now,
                now,
            ),
        )
        return relationship_id

    async def resolve_target(self, target: str) -> list[dict[str, Any]]:
        """Resolve an operator target without guessing identity."""
        self._require_started()
        target = target.strip()
        if not target:
            return []
        canonical = target.lstrip("@") if target.startswith("@") else target
        rows = await self.storage.fetchall(
            """SELECT entity_id,entity_type,canonical_value,display_value,created_at,updated_at
               FROM intel_entities
               WHERE entity_id=? OR canonical_value=? OR display_value=? OR canonical_value=?
               ORDER BY entity_type,canonical_value LIMIT ?""",
            (target, target, target, canonical, self.MAX_QUERY_ROWS),
        )
        return [dict(row) for row in rows]

    async def graph(
        self, target: str, *, limit: int = 25, offset: int = 0
    ) -> dict[str, Any] | None:
        """Return a bounded one-hop graph suitable for Telegram rendering/export."""
        self._require_started()
        bounded_limit = max(1, min(int(limit), 100))
        bounded_offset = max(0, int(offset))
        matches = await self.resolve_target(target)
        if not matches:
            return None
        if len(matches) > 1:
            return {"ambiguous": True, "candidates": matches[:20]}
        root = matches[0]
        entity_id = root["entity_id"]
        total_row = await self.storage.fetchone(
            "SELECT COUNT(*) FROM intel_relationships WHERE from_entity_id=? OR to_entity_id=?",
            (entity_id, entity_id),
        )
        rows = await self.storage.fetchall(
            """SELECT r.relationship_id,r.relationship_type,r.evidence_state,r.confidence,r.observation_id,r.created_at,r.updated_at,
                      f.entity_id AS from_id,f.entity_type AS from_type,f.canonical_value AS from_value,f.display_value AS from_display,
                      t.entity_id AS to_id,t.entity_type AS to_type,t.canonical_value AS to_value,t.display_value AS to_display
               FROM intel_relationships r
               JOIN intel_entities f ON f.entity_id=r.from_entity_id
               JOIN intel_entities t ON t.entity_id=r.to_entity_id
               WHERE r.from_entity_id=? OR r.to_entity_id=?
               ORDER BY r.confidence DESC,r.updated_at DESC,r.relationship_id
               LIMIT ? OFFSET ?""",
            (entity_id, entity_id, bounded_limit, bounded_offset),
        )
        nodes: dict[str, dict[str, Any]] = {root["entity_id"]: root}
        edges: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            nodes[item["from_id"]] = {
                "entity_id": item["from_id"],
                "entity_type": item["from_type"],
                "canonical_value": item["from_value"],
                "display_value": item["from_display"],
            }
            nodes[item["to_id"]] = {
                "entity_id": item["to_id"],
                "entity_type": item["to_type"],
                "canonical_value": item["to_value"],
                "display_value": item["to_display"],
            }
            edges.append(
                {
                    key: item[key]
                    for key in (
                        "relationship_id",
                        "relationship_type",
                        "evidence_state",
                        "confidence",
                        "observation_id",
                        "created_at",
                        "updated_at",
                        "from_id",
                        "to_id",
                    )
                }
            )
        total = int(total_row[0]) if total_row else 0
        return {
            "ambiguous": False,
            "root": root,
            "nodes": list(nodes.values()),
            "edges": edges,
            "total_edges": total,
            "offset": bounded_offset,
            "limit": bounded_limit,
            "has_more": bounded_offset + len(edges) < total,
        }

    async def evidence(self, entity_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        self._require_started()
        bounded = max(1, min(int(limit), self.MAX_QUERY_ROWS))
        rows = await self.storage.fetchall(
            "SELECT * FROM intel_observations WHERE entity_id=? ORDER BY COALESCE(observed_at,retrieved_at) DESC LIMIT ?",
            (entity_id, bounded),
        )
        return [dict(row) for row in rows]

    async def timeline(self, entity_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        """Build a bounded chronological intelligence timeline from durable evidence."""
        self._require_started()
        bounded = max(1, min(int(limit), self.MAX_QUERY_ROWS))
        observations = await self.storage.fetchall(
            """SELECT observation_id AS id,'OBSERVATION' AS kind,evidence_state,confidence,
                      COALESCE(observed_at,retrieved_at) AS timestamp,source_id,provenance_json AS payload
               FROM intel_observations WHERE entity_id=?""",
            (entity_id,),
        )
        relationships = await self.storage.fetchall(
            """SELECT relationship_id AS id,'RELATIONSHIP' AS kind,evidence_state,confidence,
                      updated_at AS timestamp,NULL AS source_id,
                      json_object('relationship_type',relationship_type,'from_entity_id',from_entity_id,'to_entity_id',to_entity_id,'observation_id',observation_id) AS payload
               FROM intel_relationships WHERE from_entity_id=? OR to_entity_id=?""",
            (entity_id, entity_id),
        )
        merged = [dict(row) for row in (*observations, *relationships)]
        merged.sort(key=lambda item: (float(item["timestamp"]), item["kind"], str(item["id"])), reverse=True)
        return merged[:bounded]

    async def ingest_text(
        self,
        *,
        source_id: str,
        source_family: str,
        text: str,
        observed_at: float | None = None,
        source_dataset: str | None = None,
        source_version: str | None = None,
        query_context: str | None = None,
    ) -> list[dict[str, Any]]:
        """Extract bounded IOCs and persist each normalized indicator as evidence."""
        self._require_started()
        if not isinstance(text, str):
            raise TypeError("text must be str")
        bounded_text = text[: self.MAX_TEXT_BYTES]
        results: list[dict[str, Any]] = []
        for indicator in extract_iocs(bounded_text):
            entity_id = await self.add_entity(
                entity_type=indicator.type,
                canonical_value=indicator.value,
                display_value=indicator.original,
            )
            observation_id = await self.add_observation(
                entity_id=entity_id,
                source_id=source_id,
                source_family=source_family,
                source_dataset=source_dataset,
                source_version=source_version,
                observed_at=observed_at,
                query_context=query_context,
                matched_field=indicator.type.lower(),
                match_type="deterministic_normalized",
                evidence_state="OBSERVED",
                confidence=1.0,
                provenance={"original": indicator.original},
            )
            results.append(
                {
                    "type": indicator.type,
                    "value": indicator.value,
                    "original": indicator.original,
                    "entity_id": entity_id,
                    "observation_id": observation_id,
                }
            )
        return results

    def _require_started(self) -> None:
        if not self._started:
            raise RuntimeError("IntelGraph is not started")
