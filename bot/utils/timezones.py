import re
from datetime import timedelta

TIMEZONE_OFFSET_RE = re.compile(r"^([+-])(?:(\d{1,2})):([0-5]\d)$")


def normalize_timezone_offset(value: str) -> str:
    """Normalize a UTC offset string to signed HH:MM format."""
    if not isinstance(value, str):
        raise ValueError("Timezone must be a string.")

    raw = value.strip().replace("UTC", "").replace("GMT", "")
    match = TIMEZONE_OFFSET_RE.match(raw)
    if not match:
        raise ValueError("Timezone must look like +05:30, -04:00, or +00:00.")

    sign, hours_text, minutes_text = match.groups()
    hours = int(hours_text)
    minutes = int(minutes_text)

    if hours > 23:
        raise ValueError("Timezone hour offset must be between 00 and 23.")

    return f"{sign}{hours:02d}:{minutes:02d}"


def timezone_offset_to_minutes(value: str) -> int:
    normalized = normalize_timezone_offset(value)
    sign = -1 if normalized.startswith("-") else 1
    hours = int(normalized[1:3])
    minutes = int(normalized[4:6])
    return sign * (hours * 60 + minutes)


def format_timezone_offset(minutes: int) -> str:
    sign = "+" if minutes >= 0 else "-"
    total = abs(minutes)
    hours = total // 60
    mins = total % 60
    return f"{sign}{hours:02d}:{mins:02d}"


def utc_label(offset_text: str) -> str:
    normalized = normalize_timezone_offset(offset_text)
    return f"UTC{normalized}"


def display_timezone_offset(offset_text: str) -> str:
    normalized = normalize_timezone_offset(offset_text)
    sign = normalized[0]
    hours = int(normalized[1:3])
    minutes = normalized[4:6]
    return f"{sign}{hours}:{minutes}"


def local_time_label(gmt_hour: int, offset_minutes: int) -> str:
    total_minutes = gmt_hour * 60 + offset_minutes
    _, minute_of_day = divmod(total_minutes, 24 * 60)
    hour = minute_of_day // 60
    minute = minute_of_day % 60
    return f"{hour:02d}:{minute:02d}"


def offset_timedelta(offset_text: str) -> timedelta:
    return timedelta(minutes=timezone_offset_to_minutes(offset_text))
