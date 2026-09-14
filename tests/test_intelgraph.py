import tempfile
import unittest

from core.services.intelgraph import IntelGraph
from core.services.storage import StorageService


class IntelGraphTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_source_entity_observation_relationship_round_trip(self):
        await self.graph.add_source(source_id="src1", source_family="family1", provider="local", source_type="telegram")
        alice = await self.graph.add_entity(entity_type="USERNAME", canonical_value="Alice", display_value="@Alice")
        bob = await self.graph.add_entity(entity_type="USERNAME", canonical_value="Bob")
        self.assertEqual(alice, await self.graph.add_entity(entity_type="USERNAME", canonical_value="Alice"))
        obs = await self.graph.add_observation(entity_id=alice, source_id="src1", source_family="family1", matched_field="username", match_type="exact", confidence=0.4, provenance={"record": "r1"})
        await self.graph.add_relationship(from_entity_id=alice, relationship_type="MENTIONS", to_entity_id=bob, evidence_state="CORRELATED", confidence=0.7, observation_id=obs)
        evidence = await self.graph.evidence(alice)
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]["evidence_state"], "OBSERVED")
        neighbors = await self.graph.neighbors(alice)
        self.assertEqual(len(neighbors), 1)
        self.assertEqual(neighbors[0]["related_entity_id"], bob)

    async def test_evidence_state_and_confidence_are_bounded(self):
        await self.graph.add_source(source_id="src1", source_family="f", provider="p", source_type="test")
        entity = await self.graph.add_entity(entity_type="DOMAIN", canonical_value="example.com")
        with self.assertRaises(ValueError):
            await self.graph.add_observation(entity_id=entity, source_id="src1", source_family="f", evidence_state="FACT")
        obs = await self.graph.add_observation(entity_id=entity, source_id="src1", source_family="f", evidence_state="DERIVED", confidence=9)
        row = await self.storage.fetchone("SELECT confidence FROM intel_observations WHERE observation_id=?", (obs,))
        self.assertEqual(row[0], 1.0)

    async def test_foreign_keys_prevent_orphan_observations(self):
        await self.graph.add_source(source_id="src1", source_family="f", provider="p", source_type="test")
        with self.assertRaises(Exception):
            await self.graph.add_observation(entity_id="missing", source_id="src1", source_family="f")
