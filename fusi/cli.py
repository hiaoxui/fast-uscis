import argparse
import json
from pathlib import Path
import sys

from fusi.cache import (
    CaseCache,
    cached_timestamp,
    load_cache,
    save_cache,
    update_timestamp,
)
from fusi.config import AccountConfig, ConfigError, load_config
from fusi.failures import (
    FailureLogError,
    append_failure,
    attempts_blocked,
    load_failures,
)
from fusi.telegram import TelegramDeliveryError, send_message_sync
from fusi.uscis import CaseUpdate, USCISChallengeError, USCISError, USCISSession

CONFIG_FILENAME = "config.toml"
CACHE_FILENAME = "case-cache.json"
FAILURE_LOG_FILENAME = "failure-log.jsonl"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m fusi",
        description="Log into every configured myUSCIS account and check all case receipts.",
    )
    parser.add_argument(
        "data_dir",
        nargs="?",
        type=Path,
        default=Path("."),
        help="Directory containing config.toml and case-cache.json.",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Run Firefox with a visible window. Useful when USCIS requires a captcha.",
    )
    parser.add_argument(
        "--sign-in-timeout-seconds",
        type=int,
        default=60,
        help="How long to wait for each USCIS login step.",
    )
    parser.add_argument(
        "--challenge-timeout-seconds",
        type=int,
        default=180,
        help="How long to wait for the AWS WAF captcha flow before failing.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    failure_log_path = args.data_dir / FAILURE_LOG_FILENAME
    try:
        failures = load_failures(failure_log_path)
    except FailureLogError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if attempts_blocked(failures):
        print(
            f"USCIS attempts are blocked after two failures within 24 hours. "
            f"Delete or empty {failure_log_path} after resolving the problem.",
            file=sys.stderr,
        )
        return 1

    app_config = None
    try:
        config_path = args.data_dir / CONFIG_FILENAME
        cache_path = args.data_dir / CACHE_FILENAME
        app_config = load_config(config_path)
        cache = load_cache(cache_path)
        outputs: list[str] = []
        for account in app_config.accounts.values():
            receipts = require_receipts(account)
            with USCISSession(
                headless=not args.headed,
                sign_in_timeout_ms=args.sign_in_timeout_seconds * 1000,
                challenge_timeout_ms=args.challenge_timeout_seconds * 1000,
            ) as session:
                session.login(account)
                for label, receipt_number in receipts.items():
                    result = session.fetch_case(receipt_number)
                    if 'error' in result.payload:
                        raise USCISError(
                            f"Error fetching case {receipt_number}: "
                            f"{result.payload['error']}"
                        )

                    output = case_output(
                        account.name,
                        label,
                        result.receipt_number,
                        result.latest_update(app_config.event_id_blacklist),
                        cache,
                    )
                    if output is not None:
                        outputs.append(output)

        save_cache(cache_path, cache)
        if not outputs:
            output = "No case updates were found."
            print(output)
            if app_config.telegram is not None:
                send_message_sync(
                    app_config.telegram,
                    app_config.telegram.no_update_chat_id,
                    output,
                )
            return 0

        for index, output in enumerate(outputs):
            if index:
                print()
            print(output)
            if app_config.telegram is not None:
                send_message_sync(
                    app_config.telegram,
                    app_config.telegram.update_chat_id,
                    output,
                )
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        if isinstance(exc, USCISChallengeError) and not args.headed:
            print(
                "Tip: re-run with --headed if you want to try solving the USCIS captcha manually.",
                file=sys.stderr,
            )
        try:
            failures = append_failure(failure_log_path, str(exc))
            blocked = attempts_blocked(failures)
        except FailureLogError as log_exc:
            print(str(log_exc), file=sys.stderr)
            blocked = False

        if app_config is not None and app_config.telegram is not None:
            message = f"fast-uscis failed: {exc}"
            if blocked:
                message += (
                    "\nFurther USCIS attempts are blocked. "
                    f"Delete or empty {failure_log_path} after resolving the problem."
                )
            try:
                send_message_sync(
                    app_config.telegram,
                    app_config.telegram.no_update_chat_id,
                    message,
                )
            except TelegramDeliveryError as telegram_exc:
                print(str(telegram_exc), file=sys.stderr)
        return 1


def require_receipts(account: AccountConfig) -> dict[str, str]:
    if not account.receipts:
        raise ConfigError(f"Account {account.name!r} does not define any receipts.")
    return account.receipts


def case_output(
    account_name: str,
    label: str,
    receipt_number: str,
    update: CaseUpdate,
    cache: CaseCache,
) -> str | None:
    was_cached, previous_timestamp = cached_timestamp(
        cache,
        account_name,
        receipt_number,
    )
    update_timestamp(cache, account_name, receipt_number, update.timestamp)

    if was_cached and previous_timestamp == update.timestamp:
        return None

    article = "an" if update.kind == "event" else "a"
    header = (
        f"{account_name} {label} got {article} {update.kind} update at "
        f"{update.timestamp}"
    )
    if update.item is None:
        return header
    return f"{header}\n{json.dumps(update.item, indent=2)}"
