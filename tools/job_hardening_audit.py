"""Read-only structural audit for the durable job-system contract."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    jobs = (ROOT / "core/services/jobs.py").read_text(encoding="utf-8")
    storage = (ROOT / "core/services/storage.py").read_text(encoding="utf-8")
    bounded = (ROOT / "core/services/bounded_jobs.py").read_text(encoding="utf-8")

    checks = {
        "payload_bound": "MAX_PAYLOAD_BYTES" in jobs and "MAX_RESULT_BYTES" in jobs,
        "metadata_bounds": all(token in jobs for token in ("MAX_JOB_TYPE_CHARS", "MAX_OWNER_CHARS", "MAX_RESOURCE_CLASS_CHARS", "MAX_IDEMPOTENCY_KEY_CHARS")),
        "durable_idempotency": "idempotency_key TEXT UNIQUE" in storage and "idempotency_key" in jobs,
        "atomic_claim": "BEGIN IMMEDIATE" in jobs and "WHERE id=? AND state=?" in jobs,
        "lease_expiry_recovery": "recover_expired" in jobs and "LEASE_EXPIRED" in jobs,
        "lease_fencing": "attempt INTEGER NOT NULL" in storage and "AND attempt=?" in jobs,
        "retry_backoff": "max_attempts" in jobs and "RETRY_SCHEDULED" in jobs and "min(300.0" in jobs,
        "persistent_failure": "JobState.FAILED" in jobs and "error_code" in jobs and "error_message" in jobs,
        "uncertain_side_effects": "JobState.UNCERTAIN" in jobs and "requeue_uncertain" in jobs,
        "bounded_shutdown": "SHUTDOWN_BUDGET_SECONDS" in bounded and "asyncio.wait(" in bounded,
        "retention_cleanup": "DEFAULT_RETENTION_SECONDS" in jobs and "async def cleanup" in jobs and "DELETE FROM jobs" in jobs,
        "event_log": "job_events" in storage and "_event_locked" in jobs,
        "attempt_history": "job_attempts" in storage and "job_attempts" in jobs,
        "migration_v3": "(3, \"\"\"" in storage and "CREATE INDEX IF NOT EXISTS idx_leases_expiry" in storage,
    }

    print("=== DURABLE JOB HARDENING AUDIT ===")
    for name, passed in checks.items():
        print(f"{name}: {'PASS' if passed else 'FAIL'}")
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        print("JOB_HARDENING_AUDIT_FAIL")
        return 1
    print("JOB_HARDENING_AUDIT_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
