from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from core.context import ApplicationContext
from core.services.jobs import JobEngine
from core.services.send_jobs import SendJobAdapter
from core.services.edit_jobs import EditJobAdapter
from core.services.delete_jobs import DeleteJobAdapter
from core.services.upload_jobs import UploadJobAdapter


def test_application_context_registers_only_SEND_EDIT_DELETE_and_UPLOAD_adapters(tmp_path: Path):
    context = ApplicationContext(SimpleNamespace(), tmp_path)

    jobs = context.get("jobs")
    assert isinstance(jobs, JobEngine)
    assert isinstance(context.get("send_jobs"), SendJobAdapter)
    assert isinstance(context.get("edit_jobs"), EditJobAdapter)
    assert isinstance(context.get("delete_jobs"), DeleteJobAdapter)
    assert isinstance(context.get("upload_jobs"), UploadJobAdapter)
    for job_type, service_name in (
        ("SEND", "send_jobs"),
        ("EDIT", "edit_jobs"),
        ("DELETE", "delete_jobs"),
        ("UPLOAD", "upload_jobs"),
    ):
        assert jobs.effect_classes[job_type] == job_type
        assert jobs.reconcilers[job_type] == context.get(service_name).reconcile

    assert jobs.effect_classes.get("JOIN") is None
    assert "JOIN" not in jobs.reconcilers
