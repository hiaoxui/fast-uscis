import json
from pathlib import Path


class CacheError(Exception):
    pass


type CaseCache = dict[str, dict[str, str | None]]


def load_cache(path: Path) -> CaseCache:
    try:
        raw_cache = json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        raise CacheError(f"Could not read case cache {path}: {exc}") from exc

    if not isinstance(raw_cache, dict):
        raise CacheError(f"Case cache {path} must contain a JSON object.")

    cache: CaseCache = {}
    for account_name, raw_cases in raw_cache.items():
        if not isinstance(account_name, str) or not isinstance(raw_cases, dict):
            raise CacheError(f"Case cache {path} has an invalid account entry.")
        cases: dict[str, str | None] = {}
        for receipt_number, timestamp in raw_cases.items():
            if not isinstance(receipt_number, str) or not (
                isinstance(timestamp, str) or timestamp is None
            ):
                raise CacheError(f"Case cache {path} has an invalid case entry.")
            cases[receipt_number] = timestamp
        cache[account_name] = cases
    return cache


def save_cache(path: Path, cache: CaseCache) -> None:
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    try:
        temporary_path.write_text(f"{json.dumps(cache, indent=2, sort_keys=True)}\n")
        temporary_path.replace(path)
    except OSError as exc:
        raise CacheError(f"Could not write case cache {path}: {exc}") from exc


def latest_updated_at(events: list[dict[str, object]]) -> str | None:
    timestamps = [
        timestamp
        for event in events
        if isinstance((timestamp := event.get("updatedAt")), str) and timestamp
    ]
    return max(timestamps, default=None)


def cached_timestamp(
    cache: CaseCache,
    account_name: str,
    receipt_number: str,
) -> tuple[bool, str | None]:
    account_cache = cache.get(account_name, {})
    if receipt_number not in account_cache:
        return False, None
    return True, account_cache[receipt_number]


def update_timestamp(
    cache: CaseCache,
    account_name: str,
    receipt_number: str,
    timestamp: str | None,
) -> None:
    cache.setdefault(account_name, {})[receipt_number] = timestamp