from pathlib import Path
import tempfile
import unittest

from fusi.config import ConfigError, load_config


class ConfigTests(unittest.TestCase):
    def test_loads_global_event_id_blacklist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text(
                """
event_id_blacklist = ["bad-event", "duplicate-event"]

[accounts.primary]
email = "user@example.com"
password = "password"
totp_secret = "secret"
"""
            )

            config = load_config(path)

        self.assertEqual(
            config.event_id_blacklist,
            frozenset({"bad-event", "duplicate-event"}),
        )

    def test_rejects_non_string_event_id_blacklist_entries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text(
                """
event_id_blacklist = ["bad-event", 123]

[accounts.primary]
email = "user@example.com"
password = "password"
totp_secret = "secret"
"""
            )

            with self.assertRaisesRegex(
                ConfigError, "event_id_blacklist must be a list"
            ):
                load_config(path)
