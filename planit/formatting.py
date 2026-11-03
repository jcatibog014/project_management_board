"""Filters for the templates: dates the way people read them."""
from datetime import date, datetime

from .dates import to_local, today, utcnow


def nice_date(moment):
    """Oct 30, 2026 (written by hand: %-d doesn't work on Windows).
    Takes a deadline (a date) or a moment from the database (naive UTC)."""
    if isinstance(moment, datetime):
        moment = to_local(moment)
    return f"{moment:%b} {moment.day}, {moment.year}"


def short_date(day):
    """Oct 30 (this year) or Oct 30, 2027."""
    if isinstance(day, datetime):
        day = to_local(day)
    return f"{day:%b} {day.day}" if day.year == today().year else nice_date(day)


def nice_datetime(moment):
    """Oct 30, 2026, 2:30 PM"""
    local = to_local(moment)
    return f"{nice_date(moment)}, {local.hour % 12 or 12}:{local:%M %p}"


def ago(moment):
    """How long ago, the way a feed says it: just now, 5 min ago, 3 h ago, Oct 30."""
    seconds = (utcnow() - moment).total_seconds()
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)} h ago"
    if seconds < 7 * 86400:
        days = int(seconds // 86400)
        return "yesterday" if days == 1 else f"{days} days ago"
    return short_date(moment)


def due_label(day):
    """Today, Tomorrow, 3 days late, Fri, Oct 30."""
    if day is None:
        return ""
    days = (day - today()).days
    if days == 0:
        return "Today"
    if days == 1:
        return "Tomorrow"
    if days == -1:
        return "Yesterday"
    if days < 0:
        return f"{-days} days late"
    if days < 7:
        return f"{day:%a}"
    return short_date(day)


def input_date(day):
    """The value a <input type="date"> wants: 2026-10-30"""
    return day.isoformat() if isinstance(day, date) else ""


def init_app(app):
    for function in (nice_date, short_date, nice_datetime, ago, due_label, input_date):
        app.jinja_env.filters[function.__name__] = function
