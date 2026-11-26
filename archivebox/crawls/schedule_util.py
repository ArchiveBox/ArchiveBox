from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from croniter import croniter


HOUR_INTERVAL = re.compile(r"([1-9][0-9]{0,5})h")

SCHEDULE_ALIASES: dict[str, str] = {
    "minute": "* * * * *",
    "minutely": "* * * * *",
    "hour": "0 * * * *",
    "hourly": "0 * * * *",
    "day": "0 0 * * *",
    "daily": "0 0 * * *",
    "week": "0 0 * * 0",
    "weekly": "0 0 * * 0",
    "month": "0 0 1 * *",
    "monthly": "0 0 1 * *",
    "year": "0 0 1 1 *",
    "yearly": "0 0 1 1 *",
}


def normalize_schedule(schedule: str) -> str:
    normalized = (schedule or "").strip()
    if not normalized:
        raise ValueError("Schedule cannot be empty.")

    return SCHEDULE_ALIASES.get(normalized.lower(), normalized)


def validate_schedule(schedule: str) -> str:
    normalized = normalize_schedule(schedule)
    if not HOUR_INTERVAL.fullmatch(normalized) and not croniter.is_valid(normalized):
        raise ValueError(
            "Invalid schedule. Use an interval like '48h', an alias like 'daily', or a cron expression like '0 */6 * * *'.",
        )
    return normalized


def next_run_for_schedule(schedule: str, after: datetime) -> datetime:
    normalized = validate_schedule(schedule)
    if interval := HOUR_INTERVAL.fullmatch(normalized):
        delay = timedelta(hours=int(interval[1]))
        # Count elapsed hours across month boundaries and daylight-saving changes.
        if after.tzinfo is not None:
            return (after.astimezone(UTC) + delay).astimezone(after.tzinfo)
        return after + delay
    return croniter(normalized, after).get_next(datetime)
