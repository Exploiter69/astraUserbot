import unittest

from tools import phase18_production_audit as audit


class Phase18HardeningGateTests(unittest.TestCase):
    def test_shutdown_audit_requires_runtime_gate(self):
        result = audit.shutdown_audit()
        self.assertTrue(result["context_closes_jobs_as_service"])
        # The legacy JobEngine implementation is no longer required to retain
        # an unbounded gather. Production must use the bounded implementation.
        self.assertFalse(result["job_close_has_unbounded_gather"])
        self.assertTrue(result["legacy_job_close_is_compatibility_only"])
        self.assertTrue(result["production_job_close_is_bounded"])
        self.assertTrue(result["runtime_gate_required"])


if __name__ == "__main__":
    unittest.main()
