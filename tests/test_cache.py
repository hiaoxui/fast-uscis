import json
from pathlib import Path
import tempfile
import unittest

from fusi.cache import (
    cached_timestamp,
    latest_updated_at,
    load_cache,
    save_cache,
    update_timestamp,
)


class CaseCacheTests(unittest.TestCase):
    def test_finds_latest_updated_at(self) -> None:
        events = [
            {"updatedAt": "2026-04-24"},
            {"updatedAt": "2026-06-24"},
            {"updatedAt": None},
        ]

        self.assertEqual(latest_updated_at(events), "2026-06-24")

    def test_distinguishes_missing_case_from_cached_none(self) -> None:
        cache: dict[str, dict[str, str | None]] = {}

        self.assertEqual(cached_timestamp(cache, "account", "IOE1"), (False, None))
        update_timestamp(cache, "account", "IOE1", None)
        self.assertEqual(cached_timestamp(cache, "account", "IOE1"), (True, None))

    def test_round_trips_all_account_timestamps(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "case-cache.json"
            cache = {
                "first": {"IOE1": "2026-06-24"},
                "second": {"IOE2": "2026-07-01"},
            }

            save_cache(path, cache)

            self.assertEqual(load_cache(path), cache)
            self.assertEqual(json.loads(path.read_text()), cache)