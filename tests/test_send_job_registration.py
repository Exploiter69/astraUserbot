from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from core.context import ApplicationContext
from core.services.jobs import JobEngine
from core.services.send_jobs import SendJobAdapter
from core.services.edit_jobs import EditJobAdapter


def test_application_context_registers_only_send_reconciliation_adapter(tmp_path: Path):
    context = ApplicationContext(SimpleNamespace(), tmp_path)

    jobs = context.get("jobs")
    assert isinstance(jobs, JobEngine)
    assert isinstance(context.get("send_jobs"), SendJobAdapter)
    assert isinstance(context.get("edit_jobs"), EditJobAdapter)
    assert jobs.effect_classes["SEND"] == "SEND"
    assert jobs.reconcilers["SEND"] == context.get("send_jobs").reconcile
    assert jobs.effect_classes["EDIT"] == "EDIT"
    assert jobs.reconcilers["EDIT"] == context.get("edit_jobs").reconcile

    for job_type in ("EDIT", "DELETE", "UPLOAD", "JOIN"):
        assert jobs.effect_classes.get(job_type) is None
        assert job_type not in jobs.reconcilers
