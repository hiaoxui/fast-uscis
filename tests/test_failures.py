from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from fusi.failures import append_failure, attempts_blocked, load_failures


class FailureLogTests(unittest.TestCase):
    def test_blocks_after_two_failures_within_24_hours_until_log_is_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "failure-log.jsonl"
            first_failure = datetime(2026, 7, 1, tzinfo=timezone.utc)

            records = append_failure(path, "first", timestamp=first_failure)
            self.assertFalse(attempts_blocked(records))

            records = append_failure(
                path,
                "second",
                timestamp=first_failure + timedelta(hours=24),
            )
            self.assertTrue(attempts_blocked(records))

            self.assertTrue(
                attempts_blocked(load_failures(path)),
                "the block must remain latched after the 24-hour window passes",
            )
            path.unlink()
            self.assertFalse(attempts_blocked(load_failures(path)))

    def test_failures_more_than_24_hours_apart_do_not_block(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "failure-log.jsonl"
            first_failure = datetime(2026, 7, 1, tzinfo=timezone.utc)
            append_failure(path, "first", timestamp=first_failure)

            records = append_failure(
                path,
                "second",
                timestamp=first_failure + timedelta(hours=24, seconds=1),
            )

            self.assertFalse(attempts_blocked(records))