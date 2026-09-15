import unittest
from types import SimpleNamespace

from helpers.hud import render
from helpers.ux import confirmation_buttons, job_buttons, progress_bar, render_job, render_jobs


class TelegramUxTests(unittest.TestCase):
    def test_progress_bar_is_bounded(self):
        self.assertEqual(progress_bar(-1), "[··········]")
        self.assertEqual(progress_bar(0.5), "[█████·····]")
        self.assertEqual(progress_bar(2), "[██████████]")

    def test_job_card_contains_durable_operator_state(self):
        job = SimpleNamespace(
            id="abcdef0123456789",
            type="TELEGRAM_ARCHIVE",
            state="RUNNING",
            progress=0.4,
            attempt_count=1,
            max_attempts=3,
            priority=4,
            resource_class="telegram_archive",
            error_code=None,
            error_message=None,
        )
        output = render_job(job)
        self.assertIn("abcdef012345", output)
        self.assertIn("TELEGRAM_ARCHIVE", output)
        self.assertIn("40%", output)
        self.assertIn("Attempt: 1/3", output)

    def test_job_controls_follow_state(self):
        running = job_buttons("a" * 32, state="RUNNING")
        failed = job_buttons("b" * 32, state="FAILED")
        completed = job_buttons("c" * 32, state="COMPLETED")
        self.assertEqual(len(running), 1)
        self.assertEqual(len(running[0]), 2)
        self.assertEqual(len(failed[0]), 2)
        self.assertEqual(len(completed[0]), 1)

    def test_confirmation_has_confirm_and_keep(self):
        buttons = confirmation_buttons("cancel", "a" * 32)
        self.assertEqual(len(buttons), 1)
        self.assertEqual(len(buttons[0]), 2)
        self.assertEqual(buttons[0][0].text, "Confirm")
        self.assertEqual(buttons[0][1].text, "Keep")

    def test_jobs_page_is_bounded(self):
        jobs = [
            SimpleNamespace(id=f"{i:032x}", type="X", state="QUEUED", progress=0.0)
            for i in range(6)
        ]
        output = render_jobs(jobs, 0, has_next=True)
        self.assertIn("Page: 1", output)
        self.assertLessEqual(len(output), 4096)

    def test_hud_stays_telegram_safe(self):
        output = render("TEST", ["x" * 10000])
        self.assertIn("output truncated", output)


if __name__ == "__main__":
    unittest.main()
