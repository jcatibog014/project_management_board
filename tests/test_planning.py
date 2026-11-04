"""Home, My Tasks, the calendars and a project's filtered list."""
from datetime import timedelta
from types import SimpleNamespace

import pytest

from planit import planning
from planit.dates import today
from planit.models import DONE, MANAGER, MEMBER, REVIEW

from .conftest import browser, make_project, make_task, make_user, post

DAY = timedelta(days=1)


@pytest.fixture
def team(app):
    owner, member, outsider = (make_user(app, name, name.title()) for name in ("olga", "mel", "otto"))
    project_id = make_project(app, owner, people={member: MEMBER})
    return SimpleNamespace(owner=owner, member=member, outsider=outsider, project=project_id)


def test_tasks_fall_into_the_right_group():
    day = today()
    def task(offset):
        return SimpleNamespace(due_date=day + offset * DAY if offset is not None else None)
    rows = [task(-1), task(0), task(3), task(10), task(None)]
    assert [name for name, _ in planning.grouped(rows, day)] == ["Overdue", "Today", "This Week", "Later", "No Date"]
    assert planning.grouped([task(6)], day)[0][0] == "This Week" and planning.grouped([task(7)], day)[0][0] == "Later"


def test_my_tasks_lists_only_my_open_tasks(app, team):
    make_task(app, team.project, team.owner, "Mine late", assignee_id=team.member, due_date=today() - DAY)
    make_task(app, team.project, team.owner, "Mine finished", status=DONE, assignee_id=team.member)
    make_task(app, team.project, team.owner, "Someone else's", assignee_id=team.owner)
    page = browser(app, team.member).get("/my-tasks").data
    assert b"Mine late" in page and b"Overdue" in page
    assert b"Mine finished" not in page and b"Someone else" not in page


def test_my_tasks_leaves_out_projects_i_left(app, team):
    make_task(app, team.project, team.owner, "Old work", assignee_id=team.member)
    post(browser(app, team.member), f"/projects/{team.project}/leave")
    assert b"Old work" not in browser(app, team.member).get("/my-tasks").data


def test_review_waits_for_managers_only(app, team):
    manager = make_user(app, "manny")
    post(browser(app, team.owner), f"/projects/{team.project}/members/add", {"username": "manny", "role": MANAGER})
    make_task(app, team.project, team.member, "Check me", status=REVIEW, assignee_id=team.member)
    assert b"Check me" in browser(app, manager).get("/my-tasks").data
    assert b"Waiting for Your Review" not in browser(app, team.member).get("/my-tasks").data


def test_home_counts(app, team):
    make_task(app, team.project, team.owner, "Late", assignee_id=team.member, due_date=today() - DAY)
    make_task(app, team.project, team.owner, "Now", assignee_id=team.member, due_date=today())
    page = browser(app, team.member).get("/").data.decode()
    assert "You have 2 open tasks" in page
    assert '<span class="stat-value">1</span><span class="stat-label">Overdue</span>' in page


def test_the_calendar_shows_my_tasks_and_project_deadlines(app, team):
    due = today() + 2 * DAY
    month = f"{due.year}-{due.month:02d}"
    make_task(app, team.project, team.owner, "On my calendar", assignee_id=team.member, due_date=due)
    make_task(app, team.project, team.owner, "Not mine", assignee_id=team.owner, due_date=due)
    page = browser(app, team.member).get(f"/calendar?month={month}").data
    assert b"On my calendar" in page and b"Not mine" not in page
    project_page = browser(app, team.member).get(f"/projects/{team.project}/calendar?month={month}").data
    assert b"On my calendar" in project_page and b"Not mine" in project_page


def test_a_bad_month_shows_this_month(app, team):
    page = browser(app, team.member).get("/calendar?month=nonsense").data.decode()
    assert f"{today():%B} {today().year}" in page


def test_outsiders_dont_see_the_project_on_their_calendar(app, team):
    due = today() + DAY
    make_task(app, team.project, team.owner, "Secret", assignee_id=team.outsider, due_date=due)
    assert b"Secret" not in browser(app, team.outsider).get(f"/calendar?month={due.year}-{due.month:02d}").data
    assert browser(app, team.outsider).get(f"/projects/{team.project}/calendar").status_code == 404


@pytest.mark.parametrize("query, shown, hidden", [
    ("who=me", [b"Mine"], [b"Theirs", b"Nobody's"]),
    ("who=nobody", [b"Nobody&#39;s"], [b"Mine"]),
    ("priority=urgent", [b"Theirs"], [b"Mine"]),
    ("status=open", [b"Mine", b"Theirs"], [b"Finished"]),
    ("status=done", [b"Finished"], [b"Mine"]),
    ("due=late", [b"Mine"], [b"Theirs"]),
    ("due=none", [b"Theirs"], [b"Mine"]),
    ("who=999&priority=nonsense", [b"Mine", b"Theirs"], []),  # bad values are ignored
])
def test_list_filters(app, team, query, shown, hidden):
    make_task(app, team.project, team.owner, "Mine", assignee_id=team.member, due_date=today() - DAY)
    make_task(app, team.project, team.owner, "Theirs", assignee_id=team.owner, priority="urgent")
    make_task(app, team.project, team.owner, "Nobody's", due_date=today() + 3 * DAY)
    make_task(app, team.project, team.owner, "Finished", status=DONE, assignee_id=team.member)
    page = browser(app, team.member).get(f"/projects/{team.project}/list?{query}").data
    for title in shown:
        assert title in page, title
    for title in hidden:
        assert title not in page, title


def test_the_list_filters_by_label(app, team):
    client = browser(app, team.owner)
    post(client, f"/projects/{team.project}/labels", {"name": "Bug", "color": "red"})
    from planit import db
    from planit.models import Label
    with app.app_context():
        bug = db.session().query(Label).filter_by(name="Bug").one().id
    post(client, f"/projects/{team.project}/tasks/new", {"title": "Bad bug", "label_ids": str(bug)})
    post(client, f"/projects/{team.project}/tasks/new", {"title": "Plain"})
    page = client.get(f"/projects/{team.project}/list?label={bug}").data
    assert b"Bad bug" in page and b"Plain" not in page


# ---------- The week view ----------

def test_week_of_starts_on_monday():
    assert planning.week_of("2026-11-04").isoformat() == "2026-11-02"
    assert planning.week_of("2026-11-02").isoformat() == "2026-11-02"
    assert planning.week_of("nonsense").weekday() == 0


def test_the_week_view_shows_every_task_of_the_week(app, team):
    monday = planning.week_of(today().isoformat())
    for n in range(5):  # more than the month's three a day
        make_task(app, team.project, team.owner, f"Task {n}", assignee_id=team.member, due_date=monday)
    make_task(app, team.project, team.owner, "Beyond the week", assignee_id=team.member, due_date=monday + 7 * DAY)
    client = browser(app, team.member)
    page = client.get(f"/calendar?week={monday.isoformat()}").data
    assert all(f"Task {n}".encode() in page for n in range(5)) and b"Beyond the week" not in page
    assert b"calendar-week" in page and b"+2 more" not in page
    assert b"+2 more" in client.get(f"/calendar?month={monday.year}-{monday.month:02d}").data
    project_page = client.get(f"/projects/{team.project}/calendar?week={monday.isoformat()}").data
    assert b"Task 4" in project_page


def test_the_week_view_buttons(app, team):
    page = browser(app, team.member).get("/calendar?week=2026-11-04").data.decode()
    assert "2 - 8 November 2026" in page
    assert "?week=2026-10-26" in page and "?week=2026-11-09" in page and "?month=2026-11" in page


# ---------- Board filters ----------

def test_the_board_filters_hide_cards_but_keep_counts(app, team):
    make_task(app, team.project, team.owner, "Urgent one", status="backlog", priority="urgent")
    make_task(app, team.project, team.owner, "Calm one", priority="low", assignee_id=team.member)
    client = browser(app, team.member)
    page = client.get(f"/projects/{team.project}?priority=urgent").data.decode()
    assert "Urgent one" in page and "Calm one" not in page
    assert "Showing 1 of 2 tasks" in page
    page = client.get(f"/projects/{team.project}?who=me").data.decode()
    assert "Calm one" in page and "Urgent one" not in page and "No tasks match" in page
    page = client.get(f"/projects/{team.project}?who=12345&priority=nonsense").data.decode()
    assert "Urgent one" in page and "Calm one" in page and "Showing" not in page
