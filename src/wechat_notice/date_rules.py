from __future__ import annotations

from datetime import date, datetime, time, timedelta, tzinfo
from zoneinfo import ZoneInfo

DateLike = date | datetime


def parse_deadline(value: DateLike | str | None) -> DateLike | None:
    """Parse the small set of date formats accepted by the notice workflow."""
    if value is None or isinstance(value, (date, datetime)):
        return value
    text = value.strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        if "T" in normalized or " " in normalized:
            return datetime.fromisoformat(normalized)
        return date.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"无法解析截止日期: {value!r}，请使用 YYYY-MM-DD 或 ISO 日期时间") from exc


def serialize_deadline(value: DateLike | str | None) -> str | None:
    if isinstance(value, str):
        value = parse_deadline(value)
    if value is None:
        return None
    return value.isoformat()


def _subtract_natural(value: DateLike, days: int) -> DateLike:
    return value - timedelta(days=days)


def _subtract_working(value: DateLike, days: int) -> DateLike:
    result = value
    remaining = days
    while remaining:
        result -= timedelta(days=1)
        if result.weekday() < 5:
            remaining -= 1
    return result


def subtract_days(value: DateLike, days: int, *, working_days: bool = False) -> DateLike:
    if days < 0:
        raise ValueError("days must be non-negative")
    if working_days:
        return _subtract_working(value, days)
    return _subtract_natural(value, days)


def calculate_class_deadline(
    original_deadline: DateLike | str | None,
    *,
    collection_required: bool,
    advance_days: int = 2,
    working_days: bool = False,
) -> DateLike | None:
    """Return the deadline shown to the class.

    Only class-wide collection uses the configurable offset. Other notices retain
    their original date. A missing deadline remains missing and is surfaced to
    review instead of being guessed.
    """
    parsed = parse_deadline(original_deadline)
    if parsed is None:
        return None
    if not collection_required:
        return parsed
    return subtract_days(parsed, advance_days, working_days=working_days)


def _timezone(name: str) -> tzinfo:
    try:
        return ZoneInfo(name)
    except Exception as exc:
        raise ValueError(f"无法使用时区: {name}") from exc


def parse_clock(value: str) -> time:
    hour, separator, minute = value.partition(":")
    if not separator or not hour.isdigit() or not minute.isdigit():
        raise ValueError("提醒时间必须使用 HH:MM")
    parsed = time(hour=int(hour), minute=int(minute))
    return parsed


def reminder_schedule(
    class_deadline: DateLike | str | None,
    offsets: list[int] | tuple[int, ...],
    *,
    reminder_time: str = "09:00",
    timezone: str = "Asia/Shanghai",
    working_days: bool = False,
) -> list[datetime]:
    """Calculate unique local reminder instants, earliest first."""
    parsed = parse_deadline(class_deadline)
    if parsed is None:
        return []
    if any(offset < 0 for offset in offsets):
        raise ValueError("提醒提前天数必须为非负整数")

    zone = _timezone(timezone)
    clock = parse_clock(reminder_time)
    if isinstance(parsed, datetime):
        local_deadline = (
            parsed.replace(tzinfo=zone)
            if parsed.tzinfo is None
            else parsed.astimezone(zone)
        )
        deadline_date = local_deadline.date()
    else:
        deadline_date = parsed
    result: set[datetime] = set()
    for offset in set(offsets):
        scheduled_date = subtract_days(deadline_date, offset, working_days=working_days)
        result.add(datetime.combine(scheduled_date, clock, tzinfo=zone))
    return sorted(result)


def format_deadline(value: DateLike | str | None) -> str:
    parsed = parse_deadline(value)
    if parsed is None:
        return "未提供"
    if isinstance(parsed, datetime):
        local = parsed.replace(tzinfo=ZoneInfo("Asia/Shanghai")) if parsed.tzinfo is None else parsed.astimezone(ZoneInfo("Asia/Shanghai"))
        return local.strftime("%Y年%m月%d日 %H:%M")
    return parsed.strftime("%Y年%m月%d日")


def is_expired(
    deadline: DateLike | str | None,
    now: datetime,
    *,
    timezone: str = "Asia/Shanghai",
) -> bool:
    """Date-only deadlines expire on the following local calendar day."""
    parsed = parse_deadline(deadline)
    if parsed is None:
        return False
    zone = _timezone(timezone)
    local_now = now.astimezone(zone) if now.tzinfo is not None else now.replace(tzinfo=zone)
    if isinstance(parsed, datetime):
        comparison = parsed
        if comparison.tzinfo is None:
            comparison = comparison.replace(tzinfo=zone)
        else:
            comparison = comparison.astimezone(zone)
        return local_now > comparison
    return local_now.date() > parsed


def collection_suggestion(original_deadline: DateLike | str | None, days: int = 2) -> str | None:
    """Suggest local noon before the source deadline without applying it."""
    parsed = parse_deadline(original_deadline)
    if parsed is None:
        return None
    zone = ZoneInfo("Asia/Shanghai")
    if isinstance(parsed, datetime):
        parsed = (parsed.replace(tzinfo=zone) if parsed.tzinfo is None else parsed.astimezone(zone)).date()
    return datetime.combine(subtract_days(parsed, days), time(12), tzinfo=zone).isoformat()
