import tempfile
import unittest

from core.services.intel_correlation import IntelCorrelationEngine
from core.services.intelgraph import IntelGraph
from core.services.storage import StorageService


class IntelGraphPhase7Tests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.storage = StorageService(self.tmp.name)
        await self.storage.start()
        self.graph = IntelGraph(self.storage)
        await self.graph.start()

    async def asyncTearDown(self):
        await self.graph.close()
        await self.storage.close()
        self.tmp.cleanup()

    async def test_graph_query_is_bounded_and_paginated(self):
        await self.graph.add_source(source_id="s", source_family="f", provider="local", source_type="test")
        root = await self.graph.add_entity(entity_type="USERNAME", canonical_value="alice")
        for index in range(15):
            other = await self.graph.add_entity(entity_type="DOMAIN", canonical_value=f"host{index}.example")
            await self.graph.add_relationship(from_entity_id=root, relationship_type="LINKS_TO", to_entity_id=other, confidence=index / 20)
        page = await self.graph.graph("@alice", limit=5, offset=5)
        self.assertEqual(page["total_edges"], 15)
        self.assertEqual(len(page["edges"]), 5)
        self.assertTrue(page["has_more"])

    async def test_graph_target_ambiguity_is_explicit(self):
        await self.graph.add_entity(entity_type="USERNAME", canonical_value="same")
        await self.graph.add_entity(entity_type="DOMAIN", canonical_value="same")
        result = await self.graph.graph("same")
        self.assertTrue(result["ambiguous"])
        self.assertEqual(len(result["candidates"]), 2)

    async def test_ingest_text_persists_normalized_ioc_evidence(self):
        await self.graph.add_source(source_id="s", source_family="telegram", provider="telegram", source_type="message")
        results = await self.graph.ingest_text(source_id="s", source_family="telegram", text="Visit https://Example.com/a and contact TEST@Example.COM; IP 192.0.2.1")
        values = {(item["type"], item["value"]) for item in results}
        self.assertIn(("DOMAIN", "example.com"), values)
        self.assertIn(("EMAIL", "test@example.com"), values)
        self.assertIn(("IP", "192.0.2.1"), values)
        row = await self.storage.fetchone("SELECT COUNT(*) FROM intel_observations")
        self.assertEqual(row[0], len(results))

    async def test_source_family_mismatch_is_rejected(self):
        await self.graph.add_source(source_id="s", source_family="family-a", provider="local", source_type="test")
        entity = await self.graph.add_entity(entity_type="DOMAIN", canonical_value="example.com")
        with self.assertRaises(ValueError):
            await self.graph.add_observation(entity_id=entity, source_id="s", source_family="family-b")

    async def test_timeline_merges_observations_and_relationships(self):
        await self.graph.add_source(source_id="s", source_family="f", provider="local", source_type="test")
        first = await self.graph.add_entity(entity_type="DOMAIN", canonical_value="first.example")
        second = await self.graph.add_entity(entity_type="DOMAIN", canonical_value="second.example")
        await self.graph.add_observation(entity_id=first, source_id="s", source_family="f", observed_at=10)
        await self.graph.add_relationship(from_entity_id=first, relationship_type="LINKS_TO", to_entity_id=second, confidence=0.8)
        timeline = await self.graph.timeline(first, limit=10)
        self.assertEqual([item["kind"] for item in timeline], ["RELATIONSHIP", "OBSERVATION"])


class IntelCorrelationPhase7Tests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.storage = StorageService(self.tmp.name)
        await self.storage.start()
        self.graph = IntelGraph(self.storage)
        await self.graph.start()
        self.engine = IntelCorrelationEngine(self.graph)

    async def asyncTearDown(self):
        await self.graph.close()
        await self.storage.close()
        self.tmp.cleanup()

    async def test_observed_relationship_stays_observed(self):
        await self.graph.add_source(source_id="s", source_family="f", provider="local", source_type="test")
        a = await self.graph.add_entity(entity_type="USERNAME", canonical_value="alice")
        b = await self.graph.add_entity(entity_type="DOMAIN", canonical_value="example.com")
        obs = await self.graph.add_observation(entity_id=a, source_id="s", source_family="f", confidence=0.9)
        relationship = await self.graph.add_relationship(from_entity_id=a, relationship_type="LINKS_TO", to_entity_id=b, evidence_state="OBSERVED", confidence=0.9, observation_id=obs)
        assessment = await self.engine.assess_relationship(relationship)
        self.assertEqual(assessment.state, "OBSERVED")
        self.assertEqual(assessment.confidence, 0.9)

    async def test_contradiction_overrides_correlation(self):
        await self.graph.add_source(source_id="s", source_family="f", provider="local", source_type="test")
        a = await self.graph.add_entity(entity_type="USERNAME", canonical_value="alice")
        b = await self.graph.add_entity(entity_type="DOMAIN", canonical_value="example.com")
        relationship = await self.graph.add_relationship(from_entity_id=a, relationship_type="LINKS_TO", to_entity_id=b, evidence_state="CORRELATED", confidence=0.7)
        await self.graph.add_observation(entity_id=a, source_id="s", source_family="f", evidence_state="CONTRADICTED", confidence=0.95)
        assessment = await self.engine.assess_relationship(relationship)
        self.assertEqual(assessment.state, "CONTRADICTED")
        self.assertEqual(assessment.confidence, 0.95)

    async def test_unknown_relationship_remains_unknown(self):
        await self.graph.add_source(source_id="s", source_family="f", provider="local", source_type="test")
        a = await self.graph.add_entity(entity_type="USERNAME", canonical_value="alice")
        b = await self.graph.add_entity(entity_type="USERNAME", canonical_value="alice2")
        relationship = await self.graph.add_relationship(from_entity_id=a, relationship_type="SHARES_USERNAME", to_entity_id=b, evidence_state="UNKNOWN")
        assessment = await self.engine.assess_relationship(relationship)
        self.assertEqual(assessment.state, "UNKNOWN")
        self.assertEqual(assessment.confidence, 0.0)
