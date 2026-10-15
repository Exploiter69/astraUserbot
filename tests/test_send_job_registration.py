from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from core.context import ApplicationContext
from core.services.jobs import JobEngine
from core.services.send_jobs import SendJobAdapter
from core.services.edit_jobs import EditJobAdapter
from core.services.delete_jobs import DeleteJobAdapter
from core.services.upload_jobs import UploadJobAdapter
from core.services.join_jobs import JoinJobAdapter


def test_application_context_registers_only_phase_3b_adapters(tmp_path: Path):
    context = ApplicationContext(SimpleNamespace(), tmp_path)

    jobs = context.get("jobs")
    assert isinstance(jobs, JobEngine)
    expected = (
        ("SEND", "send_jobs", SendJobAdapter),
        ("EDIT", "edit_jobs", EditJobAdapter),
        ("DELETE", "delete_jobs", DeleteJobAdapter),
        ("UPLOAD", "upload_jobs", UploadJobAdapter),
        ("JOIN", "join_jobs", JoinJobAdapter),
    )
    for job_type, service_name, adapter_type in expected:
        assert isinstance(context.get(service_name), adapter_type)
        assert jobs.effect_classes[job_type] == job_type
        assert jobs.reconcilers[job_type] == context.get(service_name).reconcile

    # TELEGRAM_ARCHIVE is a known pre-existing effect class, not a Phase 3B adapter.
    known_effect_classes = {"SEND", "EDIT", "DELETE", "UPLOAD", "JOIN", "TELEGRAM_ARCHIVE"}
    assert set(jobs.effect_classes) == known_effect_classes
    assert set(jobs.reconcilers) == {"SEND", "EDIT", "DELETE", "UPLOAD", "JOIN"}
