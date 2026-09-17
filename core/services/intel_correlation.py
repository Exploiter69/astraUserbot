"""Deterministic evidence classification for IntelGraph relationships.

This service deliberately does not assert identity. It classifies the evidence
already present on a relationship and its supporting observations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.services.intelgraph import EVIDENCE_STATES, IntelGraph


@dataclass(frozen=True, slots=True)
class CorrelationAssessment:
    relationship_id: str
    state: str
    confidence: float
    supporting_observation_id: str | None
    reasons: tuple[str, ...]
    contradiction_count: int


class IntelCorrelationEngine:
    """Classify explicit graph evidence without inventing identity claims."""

    MAX_OBSERVATIONS = 100

    def __init__(self, graph: IntelGraph) -> None:
        self.graph = graph

    async def assess_relationship(self, relationship_id: str) -> CorrelationAssessment:
        self.graph._require_started()
        row = await self.graph.storage.fetchone(
            """SELECT relationship_id,evidence_state,confidence,observation_id,from_entity_id,to_entity_id
               FROM intel_relationships WHERE relationship_id=?""",
            (relationship_id,),
        )
        if row is None:
            raise KeyError(relationship_id)
        relationship_state = str(row[1])
        relationship_confidence = max(0.0, min(1.0, float(row[2])))
        observation_id = row[3]
        observations = await self.graph.storage.fetchall(
            """SELECT observation_id,evidence_state,confidence,source_family,matched_field,match_type
               FROM intel_observations
               WHERE entity_id IN (?,?)
               ORDER BY confidence DESC,retrieved_at DESC LIMIT ?""",
            (row[4], row[5], self.MAX_OBSERVATIONS),
        )
        contradictions = [item for item in observations if item[1] == "CONTRADICTED"]
        supporting = [
            item for item in observations
            if item[1] in {"OBSERVED", "DERIVED", "CORRELATED", "INFERRED"}
        ]
        if relationship_state not in EVIDENCE_STATES:
            raise ValueError(f"unsupported relationship evidence state: {relationship_state}")

        reasons: list[str] = []
        if observation_id:
            reasons.append("relationship has an explicit supporting observation")
        if supporting:
            reasons.append(f"{len(supporting)} supporting observation(s) are available")
        if contradictions:
            reasons.append(f"{len(contradictions)} contradictory observation(s) are present")

        if contradictions:
            state = "CONTRADICTED"
            confidence = max(float(item[2]) for item in contradictions)
        elif observation_id and relationship_state == "OBSERVED":
            state = "OBSERVED"
            confidence = relationship_confidence
        elif relationship_state in {"DERIVED", "INFERRED", "CORRELATED"}:
            state = relationship_state
            confidence = relationship_confidence
        else:
            state = "UNKNOWN"
            confidence = 0.0
            reasons.append("no sufficient evidence for a stronger classification")

        return CorrelationAssessment(
            relationship_id=relationship_id,
            state=state,
            confidence=max(0.0, min(1.0, confidence)),
            supporting_observation_id=str(observation_id) if observation_id else None,
            reasons=tuple(reasons),
            contradiction_count=len(contradictions),
        )

    async def assess_entity(self, entity_id: str, *, limit: int = 50) -> list[CorrelationAssessment]:
        """Assess bounded adjacent relationships for an entity."""
        bounded = max(1, min(int(limit), self.graph.MAX_QUERY_ROWS))
        rows = await self.graph.storage.fetchall(
            """SELECT relationship_id FROM intel_relationships
               WHERE from_entity_id=? OR to_entity_id=?
               ORDER BY confidence DESC,updated_at DESC LIMIT ?""",
            (entity_id, entity_id, bounded),
        )
        return [await self.assess_relationship(str(row[0])) for row in rows]

    @staticmethod
    def render_assessment(assessment: CorrelationAssessment) -> dict[str, Any]:
        """Return a stable, serialization-safe diagnostic representation."""
        return {
            "relationship_id": assessment.relationship_id,
            "state": assessment.state,
            "confidence": assessment.confidence,
            "supporting_observation_id": assessment.supporting_observation_id,
            "reasons": list(assessment.reasons),
            "contradiction_count": assessment.contradiction_count,
        }
