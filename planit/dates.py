"""Times. The database always holds naive UTC; people always see Philippine time."""
from datetime import UTC, datetime, timedelta, timezone

MANILA = timezone(timedelta(hours=8))


def utcnow():
    return datetime.now(UTC).replace(tzinfo=None)


def to_local(moment):
    """Naive UTC from the database -> an aware datetime in Philippine time."""
    return moment.replace(tzinfo=UTC).astimezone(MANILA)


def parse_local(text):
    """What a <input type="datetime-local"> sends ("2026-10-30T14:30"), read as
    Philippine time -> naive UTC. Raises ValueError if it isn't a date and time."""
    return datetime.fromisoformat(text).replace(tzinfo=MANILA).astimezone(UTC).replace(tzinfo=None)


def today():
    """Today's date in the Philippines (deadlines are plain dates)."""
    return to_local(utcnow()).date()
