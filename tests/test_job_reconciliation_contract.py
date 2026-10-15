"""Regression test for replaying uncertain external effects without reconciliation."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from core.services.jobs import JobEngine, JobState
from core.services.storage import StorageService


@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=True,
    reason="JobEngine accepts ordinary handlers and requeue_uncertain() has no effect-class reconciler contract; an uncertain send can execute twice.",
)
async def test_uncertain_send_message_requires_reconciliation_before_requeue():
    with tempfile.TemporaryDirectory() as tmp:
        storage = StorageService(Path(tmp))
        await storage.start()
        engine = JobEngine(storage, worker_id="phase1-reconcile", lease_seconds=5)
        sent_messages = []
        first_effect = asyncio.Event()
        second_effect = asyncio.Event()

        async def send_message(job):
            # Fake external effect: no Telegram/network call is made.
            sent_messages.append(job.payload["text"])
            if len(sent_messages) == 1:
                first_effect.set()
                # Simulate a worker dying after the external effect but before
                # it can persist completion.
                await asyncio.Event().wait()
            second_effect.set()
            return {"sent": True}

        engine.register_handler("SEND_MESSAGE", send_message)
        try:
            queued = await engine.enqueue("SEND_MESSAGE", {"text": "synthetic message"})
            await engine.start()
            await asyncio.wait_for(first_effect.wait(), timeout=1.0)

            # Closing interrupts the handler after the fake send. The engine
            # records an uncertain outcome, not a completed job.
            await engine.close()
            uncertain = await engine.get(queued.id)
            assert uncertain.state == JobState.UNCERTAIN

            # Current API permits replay without any effect-specific observer.
            await engine.requeue_uncertain(queued.id)
            await engine.start()
            await asyncio.wait_for(second_effect.wait(), timeout=1.0)
            await asyncio.sleep(0.02)

            assert sent_messages == ["synthetic message"], (
                "uncertain external mutation replayed without reconciliation; "
                f"observed sends={len(sent_messages)}"
            )
        finally:
            await engine.close()
            await storage.close()
