import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

from core.household import STALE_AFTER, is_active, summarise_jobs

NOW = datetime(2026, 10, 30, 18, 0, 0)


def job(jid, conn, kind, status, minutes_ago=1, step=None, processed=0, total=0, error=None):
    when = NOW - timedelta(minutes=minutes_ago)
    return SimpleNamespace(
        id=jid, connection_id=conn, job_type=kind, status=status, current_step=step,
        processed_items=processed, total_items=total, error_message=error, updated_at=when, created_at=when,
    )


class IsActiveTests(unittest.TestCase):
    def test_pending_and_running_are_active(self) -> None:
        self.assertTrue(is_active("pending", NOW, NOW))
        self.assertTrue(is_active("running", NOW - timedelta(minutes=10), NOW))

    def test_finished_jobs_are_not_active(self) -> None:
        for s in ("completed", "failed", "cancelled"):
            self.assertFalse(is_active(s, NOW, NOW))

    def test_a_job_silent_for_hours_is_treated_as_dead(self) -> None:
        self.assertFalse(is_active("running", NOW - STALE_AFTER - timedelta(minutes=1), NOW))

    def test_enum_like_status_values_work(self) -> None:
        self.assertTrue(is_active(SimpleNamespace(value="running"), NOW, NOW))


class SummariseJobsTests(unittest.TestCase):
    def test_latest_job_and_last_success_are_kept_per_connection_and_kind(self) -> None:
        jobs = [  # newest first
            job(5, 1, "pull", "running", 1, "Pulling movies", 10, 100),
            job(4, 1, "push", "failed", 5, error="boom"),
            job(3, 1, "pull", "completed", 30),
            job(2, 2, "pull", "completed", 90),
            job(1, 1, "pull", "completed", 600),
        ]
        out = summarise_jobs(jobs, NOW)
        pull = out[1]["pull"]
        self.assertEqual(pull["latest"]["id"], 5)
        self.assertTrue(pull["latest"]["active"])
        self.assertEqual((pull["latest"]["step"], pull["latest"]["processed"], pull["latest"]["total"]), ("Pulling movies", 10, 100))
        self.assertEqual(pull["last_ok_at"], (NOW - timedelta(minutes=30)).isoformat())
        push = out[1]["push"]
        self.assertEqual(push["latest"]["status"], "failed")
        self.assertEqual(push["latest"]["error"], "boom")
        self.assertIsNone(push["last_ok_at"])
        self.assertEqual(out[2]["pull"]["latest"]["id"], 2)
        self.assertNotIn("push", out[2])

    def test_jobs_without_a_connection_or_of_other_kinds_are_ignored(self) -> None:
        jobs = [job(1, None, "pull", "completed"), job(2, 1, "heal", "completed")]
        self.assertEqual(summarise_jobs(jobs, NOW), {})


if __name__ == "__main__":
    unittest.main()
