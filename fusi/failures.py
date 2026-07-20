from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

FAILURE_WINDOW = timedelta(hours=24)


class FailureLogError(Exception):
    pass


@dataclass(frozen=True)
class FailureRecord:
    timestamp: datetime
    error: str


def load_failures(path: Path) -> list[FailureRecord]:
    try:
        lines = path.read_text().splitlines()
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise FailureLogError(f"Could not read failure log {path}: {exc}") from exc

    records: list[FailureRecord] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            raw_record = json.loads(line)
            timestamp = datetime.fromisoformat(raw_record["timestamp"])
            error = raw_record["error"]
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise FailureLogError(
                f"Invalid failure log entry at {path}:{line_number}."
            ) from exc
        if timestamp.tzinfo is None or not isinstance(error, str):
            raise FailureLogError(
                f"Invalid failure log entry at {path}:{line_number}."
            )
        records.append(FailureRecord(timestamp=timestamp, error=error))
    return records


def append_failure(
    path: Path,
    error: str,
    *,
    timestamp: datetime | None = None,
) -> list[FailureRecord]:
    recorded_at = timestamp or datetime.now(timezone.utc)
    record = {
        "timestamp": recorded_at.isoformat(),
        "error": error,
    }
    try:
        with path.open("a") as failure_log:
            failure_log.write(f"{json.dumps(record)}\n")
    except OSError as exc:
        raise FailureLogError(f"Could not write failure log {path}: {exc}") from exc
    return load_failures(path)


def attempts_blocked(records: list[FailureRecord]) -> bool:
    timestamps = sorted(record.timestamp for record in records)
    return any(
        later - earlier <= FAILURE_WINDOW
        for earlier, later in zip(timestamps, timestamps[1:])
    )