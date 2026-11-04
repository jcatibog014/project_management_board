"""The project Dashboard: numbers and the shapes of its charts.

The charts are SVG drawn by the server (project/dashboard.html), so there is
no chart library and nothing to download. This module works out the numbers;
bar() turns a number into a bar with a rounded end (the end away from the
baseline, so every bar starts from a straight edge).

The status colours were checked with the dataviz validator (light and dark):
every pair of neighbouring columns is easy to tell apart, and every bar also
carries its number, so colour is never the only clue.
"""
from dataclasses import dataclass
from datetime import timedelta

from . import projects, workflow
from .dates import to_local, today
from .models import DONE, IN_PROGRESS, REVIEW, TODO

WEEKS = 8
WORKLOAD_STATUSES = (TODO, IN_PROGRESS, REVIEW)


@dataclass
class Summary:
    total: int
    done: int
    open: int
    overdue: int
    finished_this_week: int

    @property
    def percent(self):
        return round(100 * self.done / self.total) if self.total else 0


def summary(rows, day=None):
    day = day or today()
    week_ago = day - timedelta(days=6)
    done = [task for task in rows if task.status == DONE]
    return Summary(
        total=len(rows), done=len(done), open=len(rows) - len(done),
        overdue=sum(1 for task in rows if task.status != DONE and task.due_date and task.due_date < day),
        finished_this_week=sum(1 for task in done
                               if task.completed_at and to_local(task.completed_at).date() >= week_ago))


def by_status(rows):
    """[(status, name, count)] in workflow order."""
    counts = {status: 0 for status in workflow.STATUSES}
    for task in rows:
        counts[task.status] += 1
    return [(status, workflow.name(status), counts[status]) for status in workflow.STATUSES]


def workload(s, project, rows):
    """[(user or None, {status: count}, total)]: open, started work per person, busiest first.
    Everyone who can be given tasks is listed, even with nothing to do."""
    people = {user.id: user for user in projects.assignable(s, project)}
    loads = {user_id: {status: 0 for status in WORKLOAD_STATUSES} for user_id in people}
    nobody = {status: 0 for status in WORKLOAD_STATUSES}
    for task in rows:
        if task.status not in WORKLOAD_STATUSES:
            continue
        if task.assignee_id in loads:
            loads[task.assignee_id][task.status] += 1
        elif task.assignee_id is None:
            nobody[task.status] += 1
    result = [(people[user_id], counts, sum(counts.values())) for user_id, counts in loads.items()]
    result.sort(key=lambda row: (-row[2], row[0].display_name.lower()))
    if sum(nobody.values()):
        result.append((None, nobody, sum(nobody.values())))
    return result


def weekly(rows, day=None, weeks=WEEKS):
    """[(monday, count)] of tasks finished in each of the last `weeks` weeks, oldest first."""
    day = day or today()
    this_monday = day - timedelta(days=day.weekday())
    mondays = [this_monday - timedelta(weeks=n) for n in range(weeks - 1, -1, -1)]
    counts = dict.fromkeys(mondays, 0)
    for task in rows:
        if task.status == DONE and task.completed_at:
            finished = to_local(task.completed_at).date()
            monday = finished - timedelta(days=finished.weekday())
            if monday in counts:
                counts[monday] += 1
    return list(counts.items())


def upcoming(rows, day=None, limit=6):
    """Open tasks with a deadline, the soonest (or latest overdue) first."""
    day = day or today()
    dated = [task for task in rows if task.status != DONE and task.due_date]
    return sorted(dated, key=lambda task: task.due_date)[:limit]


def bar(x, y, width, height, end="right", radius=4):
    """An SVG path for a bar whose far end is rounded and whose base is square."""
    if width <= 0 or height <= 0:
        return ""
    r = min(radius, width, height / 2) if end == "right" else min(radius, width / 2, height)
    if end == "right":
        return (f"M{x:.1f},{y:.1f} h{width - r:.1f} a{r},{r} 0 0 1 {r},{r} v{height - 2 * r:.1f} "
                f"a{r},{r} 0 0 1 -{r},{r} h-{width - r:.1f} z")
    # end == "top": a column standing on the baseline at y + height.
    return (f"M{x:.1f},{y + height:.1f} v-{height - r:.1f} a{r},{r} 0 0 1 {r},-{r} h{width - 2 * r:.1f} "
            f"a{r},{r} 0 0 1 {r},{r} v{height - r:.1f} z")


def init_app(app):
    app.jinja_env.globals["bar_path"] = bar
