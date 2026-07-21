from io import StringIO
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from fusi.cli import build_parser, case_output, main
from fusi.config import AccountConfig, AppConfig, TelegramConfig
from fusi.failures import FailureRecord
from fusi.uscis import USCISLoginError
from datetime import datetime, timezone


class CaseOutputTests(unittest.TestCase):
    def test_first_run_then_unchanged_then_updated(self) -> None:
        cache: dict[str, dict[str, str | None]] = {}
        original_events = [{"updatedAt": "2026-06-24", "eventCode": "FTA0"}]

        first_output = case_output(
            "primary", "I-485", "IOE1", original_events, cache
        )
        unchanged_output = case_output(
            "primary", "I-485", "IOE1", original_events, cache
        )
        updated_events = [{"updatedAt": "2026-07-19", "eventCode": "NEW"}]
        updated_output = case_output(
            "primary", "I-485", "IOE1", updated_events, cache
        )

        self.assertEqual(first_output, json.dumps(original_events, indent=2))
        self.assertIsNone(unchanged_output)
        self.assertEqual(
            updated_output,
            "primary I-485 got an update at 2026-07-19\n"
            f"{json.dumps(updated_events, indent=2)}",
        )
        self.assertEqual(cache["primary"]["IOE1"], "2026-07-19")


class ParserTests(unittest.TestCase):
    def test_accepts_data_directory(self) -> None:
        args = build_parser().parse_args(["/var/lib/fusi"])

        self.assertEqual(args.data_dir, Path("/var/lib/fusi"))


class MainTests(unittest.TestCase):
    def test_scans_all_accounts_and_prints_one_unchanged_summary(self) -> None:
        first_account = AccountConfig(
            name="first",
            email="user@example.com",
            password="password",
            totp_secret="secret",
            receipts={"I-485": "IOE1"},
        )
        second_account = AccountConfig(
            name="second",
            email="second@example.com",
            password="password",
            totp_secret="secret",
            receipts={"I-765": "IOE2"},
        )
        telegram = TelegramConfig(
            api="token",
            update_chat_id="updates",
            no_update_chat_id="no-updates",
        )
        app_config = AppConfig(
            accounts={"first": first_account, "second": second_account},
            telegram=telegram,
        )
        cache = {
            "first": {"IOE1": "2026-06-24"},
            "second": {"IOE2": "2026-07-01"},
        }
        first_result = SimpleNamespace(
            payload={"data": {}},
            receipt_number="IOE1",
            events=[{"updatedAt": "2026-06-24"}],
        )
        second_result = SimpleNamespace(
            payload={"data": {}},
            receipt_number="IOE2",
            events=[{"updatedAt": "2026-07-01"}],
        )

        with (
            patch("fusi.cli.load_config", return_value=app_config),
            patch("fusi.cli.load_cache", return_value=cache),
            patch("fusi.cli.save_cache") as save_cache_mock,
            patch("fusi.cli.send_message_sync") as send_message_mock,
            patch("fusi.cli.USCISSession") as session_class,
            patch("sys.stdout", new_callable=StringIO) as stdout,
        ):
            first_session = MagicMock()
            first_session.fetch_case.return_value = first_result
            first_context = MagicMock()
            first_context.__enter__.return_value = first_session
            second_session = MagicMock()
            second_session.fetch_case.return_value = second_result
            second_context = MagicMock()
            second_context.__enter__.return_value = second_session
            session_class.side_effect = [first_context, second_context]

            exit_code = main(["/var/lib/fusi"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout.getvalue(), "No case updates were found.\n")
        send_message_mock.assert_called_once_with(
            telegram,
            "no-updates",
            "No case updates were found.",
        )
        first_session.login.assert_called_once_with(first_account)
        first_session.fetch_case.assert_called_once_with("IOE1")
        second_session.login.assert_called_once_with(second_account)
        second_session.fetch_case.assert_called_once_with("IOE2")
        save_cache_mock.assert_called_once_with(
            Path("/var/lib/fusi/case-cache.json"),
            cache,
        )

    def test_aborts_before_loading_config_when_failure_guard_is_latched(self) -> None:
        timestamp = datetime(2026, 7, 19, tzinfo=timezone.utc)
        failures = [
            FailureRecord(timestamp=timestamp, error="first"),
            FailureRecord(timestamp=timestamp, error="second"),
        ]

        with (
            patch("fusi.cli.load_failures", return_value=failures),
            patch("fusi.cli.load_config") as load_config_mock,
            patch("fusi.cli.USCISSession") as session_class,
            patch("sys.stderr", new_callable=StringIO) as stderr,
        ):
            exit_code = main(["/var/lib/fusi"])

        self.assertEqual(exit_code, 1)
        self.assertIn("attempts are blocked", stderr.getvalue())
        load_config_mock.assert_not_called()
        session_class.assert_not_called()

    def test_records_failure_and_notifies_when_second_failure_latches_guard(self) -> None:
        account = AccountConfig(
            name="first",
            email="user@example.com",
            password="password",
            totp_secret="secret",
            receipts={"I-485": "IOE1"},
        )
        telegram = TelegramConfig(
            api="token",
            update_chat_id="updates",
            no_update_chat_id="no-updates",
        )
        app_config = AppConfig(accounts={"first": account}, telegram=telegram)
        timestamp = datetime(2026, 7, 19, tzinfo=timezone.utc)
        failures = [
            FailureRecord(timestamp=timestamp, error="first"),
            FailureRecord(timestamp=timestamp, error="login failed"),
        ]

        with (
            patch("fusi.cli.load_failures", return_value=[]),
            patch("fusi.cli.load_config", return_value=app_config),
            patch("fusi.cli.load_cache", return_value={}),
            patch("fusi.cli.append_failure", return_value=failures) as append_mock,
            patch("fusi.cli.send_message_sync") as send_message_mock,
            patch("fusi.cli.USCISSession") as session_class,
            patch("sys.stderr", new_callable=StringIO),
        ):
            session = MagicMock()
            session.login.side_effect = USCISLoginError("login failed")
            session_class.return_value.__enter__.return_value = session

            exit_code = main(["/var/lib/fusi"])

        self.assertEqual(exit_code, 1)
        append_mock.assert_called_once_with(
            Path("/var/lib/fusi/failure-log.jsonl"),
            "login failed",
        )
        self.assertEqual(send_message_mock.call_args.args[1], "updates")
        notification = send_message_mock.call_args.args[2]
        self.assertIn("fast-uscis failed: login failed", notification)
        self.assertIn("Further USCIS attempts are blocked", notification)