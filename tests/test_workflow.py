"""The workflow: which moves are allowed, for whom, and what they leave behind."""
from types import SimpleNamespace

import pytest

from planit import permissions as can, workflow
from planit.models import BACKLOG, DONE, IN_PROGRESS, MANAGER, MEMBER, OWNER, REVIEW, TODO, VIEWER

from .conftest import browser, get_task, make_project, make_task, make_user, post

ME, SOMEONE = 1, 2


def access(role, archived=False):
    project = SimpleNamespace(id=10, owner_id=ME if role == OWNER else 99, is_team=True, is_archived=archived)
    return can.Access(SimpleNamespace(id=ME, is_demo=False), project, role)


def task(status, assignee=ME):
    return SimpleNamespace(status=status, assignee_id=assignee, reporter_id=SOMEONE)


OK = None
#   role,    from,        to,          assignee, problem (a word from the message, or OK)
TABLE = [
    # The allowed paths, for a Manager.
    (MANAGER, BACKLOG, TODO, ME, OK),
    (MANAGER, TODO, BACKLOG, ME, OK),
    (MANAGER, TODO, IN_PROGRESS, ME, OK),
    (MANAGER, IN_PROGRESS, TODO, ME, OK),
    (MANAGER, IN_PROGRESS, REVIEW, ME, OK),
    (MANAGER, REVIEW, IN_PROGRESS, ME, OK),
    (MANAGER, REVIEW, DONE, ME, OK),
    (MANAGER, DONE, TODO, ME, OK),
    # No skipping steps, for anyone.
    (OWNER, TODO, DONE, ME, "straight"),
    (OWNER, BACKLOG, IN_PROGRESS, ME, "straight"),
    (OWNER, IN_PROGRESS, DONE, ME, "straight"),
    (OWNER, DONE, REVIEW, ME, "straight"),
    # A task needs someone before work starts.
    (MANAGER, TODO, IN_PROGRESS, None, "Give the task"),
    # Members: only their own tasks, and they can't approve or reopen.
    (MEMBER, TODO, IN_PROGRESS, ME, OK),
    (MEMBER, IN_PROGRESS, REVIEW, ME, OK),
    (MEMBER, REVIEW, IN_PROGRESS, ME, OK),
    (MEMBER, REVIEW, DONE, ME, "approve"),
    (MEMBER, DONE, TODO, ME, "reopen"),
    (MEMBER, TODO, IN_PROGRESS, SOMEONE, "given to them"),
    (MEMBER, BACKLOG, TODO, None, "given to them"),
    # Viewers move nothing.
    (VIEWER, BACKLOG, TODO, ME, "Viewers"),
    (VIEWER, REVIEW, DONE, ME, "Viewers"),
    (None, BACKLOG, TODO, ME, "can't"),
]


@pytest.mark.parametrize("role, before, to, assignee, problem", TABLE)
def test_move_rules(role, before, to, assignee, problem):
    answer = workflow.move_problem(access(role), task(before, assignee), to)
    if problem is OK:
        assert answer is None
    else:
        assert answer and problem in answer


def test_nothing_moves_in_an_archived_project():
    assert "archived" in workflow.move_problem(access(OWNER, archived=True), task(TODO), BACKLOG)


def test_allowed_moves_are_the_buttons_to_show():
    assert workflow.allowed_moves(access(MANAGER), task(REVIEW)) == [(IN_PROGRESS, "Send back"), (DONE, "Approve")]
    assert workflow.allowed_moves(access(MEMBER), task(REVIEW)) == [(IN_PROGRESS, "Send back")]
    assert workflow.allowed_moves(access(VIEWER), task(TODO)) == []


# ---------- Through the routes ----------

@pytest.fixture
def team(app):
    owner, manager, member = (make_user(app, name) for name in ("olga", "manny", "mel"))
    project_id = make_project(app, owner, people={manager: MANAGER, member: MEMBER})
    return SimpleNamespace(owner=owner, manager=manager, member=member, project=project_id)


def move(app, user_id, project_id, number, to, as_json=False):
    headers = {"Accept": "application/json"} if as_json else {}
    return post(browser(app, user_id), f"/projects/{project_id}/tasks/{number}/move", {"to": to}, headers=headers)


def test_a_task_travels_the_whole_workflow(app, team):
    number = make_task(app, team.project, team.member, assignee_id=team.member)
    for to in (IN_PROGRESS, REVIEW):
        assert move(app, team.member, team.project, number, to).status_code == 302
    assert move(app, team.member, team.project, number, DONE).status_code == 302
    assert get_task(app, team.project, number).status == REVIEW  # refused: a Member can't approve
    move(app, team.manager, team.project, number, DONE)
    done = get_task(app, team.project, number)
    assert done.status == DONE and done.completed_at is not None
    move(app, team.manager, team.project, number, TODO)
    reopened = get_task(app, team.project, number)
    assert reopened.status == TODO and reopened.completed_at is None


def test_drag_and_drop_gets_json(app, team):
    number = make_task(app, team.project, team.member, assignee_id=team.member)
    good = move(app, team.member, team.project, number, IN_PROGRESS, as_json=True)
    assert good.status_code == 200 and good.json["ok"]
    bad = move(app, team.member, team.project, number, DONE, as_json=True)
    assert bad.status_code == 409 and "straight" in bad.json["message"]


def test_a_full_column_takes_no_more(app, team):
    post(browser(app, team.manager), f"/projects/{team.project}/limits", {"limit_in_progress": "1"})
    first = make_task(app, team.project, team.manager, assignee_id=team.manager)
    second = make_task(app, team.project, team.manager, assignee_id=team.manager)
    move(app, team.manager, team.project, first, IN_PROGRESS)
    answer = move(app, team.manager, team.project, second, IN_PROGRESS, as_json=True)
    assert answer.status_code == 409 and "full" in answer.json["message"]
    assert get_task(app, team.project, second).status == TODO
    # Clearing the limit lets it through.
    post(browser(app, team.manager), f"/projects/{team.project}/limits", {"limit_in_progress": ""})
    assert move(app, team.manager, team.project, second, IN_PROGRESS, as_json=True).status_code == 200


def test_members_cant_set_limits(app, team):
    assert post(browser(app, team.member), f"/projects/{team.project}/limits",
                {"limit_review": "2"}).status_code == 403


def test_every_move_is_in_the_history(app, team):
    number = make_task(app, team.project, team.member, assignee_id=team.member)
    move(app, team.member, team.project, number, IN_PROGRESS)
    page = browser(app, team.owner).get(f"/projects/{team.project}/activity").data
    assert b"moved" in page and b"from To Do to In Progress" in page


def test_the_board_shows_only_the_moves_you_may_make(app, team):
    number = make_task(app, team.project, team.owner, "Approve me", status=REVIEW, assignee_id=team.member)
    member_board = browser(app, team.member).get(f"/projects/{team.project}").data.decode()
    manager_board = browser(app, team.manager).get(f"/projects/{team.project}").data.decode()
    assert f'id="task-{number}"' in member_board
    assert 'data-moves="in_progress done"' in manager_board
    assert 'data-moves="in_progress"' in member_board


def test_sending_back_from_review_writes_its_own_history(app):
    """Send back (In Review -> In Progress) has its own words in the history."""
    owner, member = make_user(app, "olga"), make_user(app, "mel")
    project = make_project(app, owner, people={member: MEMBER})
    number = make_task(app, project, owner, "Check me", status="review", assignee_id=member)
    response = post(browser(app, owner), f"/projects/{project}/tasks/{number}/move", {"to": "in_progress"})
    assert response.status_code == 302
    assert b"back to In Progress" in browser(app, owner).get(f"/projects/{project}/activity").data
