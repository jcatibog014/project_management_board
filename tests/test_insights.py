"""The project Dashboard: its numbers, its chart shapes, and who can see it."""
from datetime import datetime, time, timedelta
from types import SimpleNamespace

from planit import insights
from planit.dates import today
from planit.models import DONE, IN_PROGRESS, MEMBER, REVIEW, TODO, VIEWER

from .conftest import browser, make_project, make_task, make_user

DAY = timedelta(days=1)


def task(status=TODO, due=None, finished_days_ago=None, assignee=None):
    completed = None
    if finished_days_ago is not None:
        # Noon in Manila on that day, stored as naive UTC like the database does (Manila is UTC+8).
        completed = datetime.combine(today() - finished_days_ago * DAY, time(12)) - timedelta(hours=8)
    return SimpleNamespace(status=status, due_date=due, completed_at=completed, assignee_id=assignee)


def test_summary_counts():
    rows = [task(DONE, finished_days_ago=1), task(DONE, finished_days_ago=20), task(TODO, due=today() - DAY),
            task(IN_PROGRESS, due=today() + DAY)]
    summary = insights.summary(rows)
    assert (summary.total, summary.done, summary.open, summary.overdue, summary.percent) == (4, 2, 2, 1, 50)
    assert summary.finished_this_week == 1
    assert insights.summary([]).percent == 0


def test_by_status_lists_every_column_in_order():
    rows = [task(REVIEW), task(REVIEW), task(DONE)]
    assert [(status, count) for status, _, count in insights.by_status(rows)] == [
        ("backlog", 0), ("todo", 0), ("in_progress", 0), ("review", 2), ("done", 1)]


def test_weekly_puts_finished_tasks_in_their_week():
    weeks = insights.weekly([task(DONE, finished_days_ago=0), task(DONE, finished_days_ago=0),
                             task(DONE, finished_days_ago=200)])
    assert len(weeks) == insights.WEEKS
    assert weeks[-1][1] == 2  # this week
    assert sum(count for _, count in weeks) == 2  # too old to show
    assert all(monday.weekday() == 0 for monday, _ in weeks)


def test_upcoming_skips_done_and_undated():
    soon, later = task(TODO, due=today() + DAY), task(TODO, due=today() + 5 * DAY)
    rows = [later, task(DONE, due=today()), task(TODO), soon]
    assert insights.upcoming(rows) == [soon, later]


def test_bars_have_a_square_base_and_a_rounded_end():
    right = insights.bar(10, 0, 100, 24)
    assert right.startswith("M10.0,0.0") and " a4,4 " in right
    assert insights.bar(0, 0, 0, 24) == ""
    tiny = insights.bar(0, 0, 3, 24)  # narrower than the corner: the corner shrinks
    assert "a3,3" in tiny
    top = insights.bar(0, 100, 36, 60, end="top")
    assert top.startswith("M0.0,160.0")


def test_workload_counts_open_work_per_person(app):
    owner, member, viewer = (make_user(app, name, name.title()) for name in ("olga", "mel", "vic"))
    project_id = make_project(app, owner, people={member: MEMBER, viewer: VIEWER})
    make_task(app, project_id, owner, "a", status=IN_PROGRESS, assignee_id=member)
    make_task(app, project_id, owner, "b", status=REVIEW, assignee_id=member)
    make_task(app, project_id, owner, "c", status=DONE, assignee_id=member)  # finished: not workload
    make_task(app, project_id, owner, "d", status=TODO)  # nobody yet
    page = browser(app, owner).get(f"/projects/{project_id}/dashboard").data.decode()
    assert "Mel: To Do 0, In Progress 1, In Review 1" in page
    assert "Nobody yet" in page
    assert "Vic:" not in page  # Viewers can't be given tasks, so they have no workload row


def test_everyone_in_the_project_sees_the_dashboard_and_outsiders_dont(app):
    owner, viewer, outsider = (make_user(app, name) for name in ("olga", "vic", "otto"))
    project_id = make_project(app, owner, people={viewer: VIEWER})
    make_task(app, project_id, owner, "Something")
    assert b"Tasks by Status" in browser(app, viewer).get(f"/projects/{project_id}/dashboard").data
    assert browser(app, outsider).get(f"/projects/{project_id}/dashboard").status_code == 404


def test_an_empty_project_says_so(app):
    owner = make_user(app, "olga")
    project_id = make_project(app, owner)
    assert b"The charts fill in" in browser(app, owner).get(f"/projects/{project_id}/dashboard").data
