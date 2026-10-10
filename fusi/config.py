from dataclasses import dataclass
from pathlib import Path
import tomllib


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class AccountConfig:
    name: str
    email: str
    password: str
    totp_secret: str
    receipts: dict[str, str]


@dataclass(frozen=True)
class TelegramConfig:
    api: str
    update_chat_id: str
    no_update_chat_id: str


@dataclass(frozen=True)
class AppConfig:
    accounts: dict[str, AccountConfig]
    telegram: TelegramConfig | None
    event_id_blacklist: frozenset[str] = frozenset()


def load_config(path: Path) -> AppConfig:
    try:
        data = tomllib.loads(path.read_text())
    except FileNotFoundError as exc:
        raise ConfigError(f"Config file not found: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        message = (
            f"Invalid TOML in {path}: {exc}. "
            "Check for duplicate tables or malformed account entries."
        )
        raise ConfigError(message) from exc

    raw_accounts = data.get("accounts")
    if not isinstance(raw_accounts, dict) or not raw_accounts:
        raise ConfigError(f"{path} must define a non-empty [accounts] table.")

    accounts: dict[str, AccountConfig] = {}
    for name, raw_account in raw_accounts.items():
        if not isinstance(raw_account, dict):
            raise ConfigError(f"Account {name!r} must be a table.")

        email = _require_string(raw_account, "email", account_name=name)
        password = _require_string(raw_account, "password", account_name=name)
        totp_secret = _require_string(raw_account, "totp_secret", account_name=name)
        receipts = _load_receipts(raw_account, account_name=name)
        accounts[name] = AccountConfig(
            name=name,
            email=email,
            password=password,
            totp_secret=totp_secret,
            receipts=receipts,
        )

    return AppConfig(
        accounts=accounts,
        telegram=_load_telegram(data),
        event_id_blacklist=_load_event_id_blacklist(data),
    )


def _load_event_id_blacklist(data: dict[str, object]) -> frozenset[str]:
    raw_blacklist = data.get("event_id_blacklist", [])
    if not isinstance(raw_blacklist, list) or not all(
        isinstance(event_id, str) and event_id for event_id in raw_blacklist
    ):
        raise ConfigError("event_id_blacklist must be a list of non-empty strings.")
    return frozenset(raw_blacklist)


def _load_telegram(data: dict[str, object]) -> TelegramConfig | None:
    raw_telegram = data.get("telegram")
    if raw_telegram is None:
        return None
    if not isinstance(raw_telegram, dict):
        raise ConfigError("Telegram configuration must be a table.")

    api = _require_config_string(raw_telegram, "api", section="telegram")
    update_chat_id = _require_config_string(
        raw_telegram,
        "update_chat_id",
        section="telegram",
    )
    no_update_chat_id = _require_config_string(
        raw_telegram,
        "no_update_chat_id",
        section="telegram",
    )
    return TelegramConfig(
        api=api,
        update_chat_id=update_chat_id,
        no_update_chat_id=no_update_chat_id,
    )


def _load_receipts(raw_account: dict[str, object], *, account_name: str) -> dict[str, str]:
    raw_receipts = raw_account.get("receipts")
    if raw_receipts is None:
        return {}
    if not isinstance(raw_receipts, dict):
        raise ConfigError(f"Account {account_name!r} receipts must be a table.")

    receipts: dict[str, str] = {}
    for label, value in raw_receipts.items():
        if not isinstance(label, str) or not isinstance(value, str):
            raise ConfigError(
                f"Account {account_name!r} receipt entries must map strings to strings."
            )
        receipts[label] = value
    return receipts


def _require_string(
    raw_account: dict[str, object],
    key: str,
    *,
    account_name: str,
) -> str:
    value = raw_account.get(key)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"Account {account_name!r} is missing {key!r}.")
    return value


def _require_config_string(
    table: dict[str, object],
    key: str,
    *,
    section: str,
) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"[{section}] is missing {key!r}.")
    return value
