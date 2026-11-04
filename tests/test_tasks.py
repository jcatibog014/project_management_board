"""Making, editing, assigning and deleting tasks, and who may do each."""
from types import SimpleNamespace

import pytest

from planit.models import BACKLOG, DONE, MANAGER, MEMBER, PERSONAL, TODO, VIEWER

from .conftest import browser, get_task, make_project, make_task, make_user, post


@pytest.fixture
def team(app):
    owner, manager, member, viewer, other = (make_user(app, name, name.title())
                                             for name in ("olga", "manny", "mel", "vic", "mo"))
    project_id = make_project(app, owner, people={manager: MANAGER, member: MEMBER, viewer: VIEWER, other: MEMBER})
    return SimpleNamespace(owner=owner, manager=manager, member=member, viewer=viewer, other=other,
                           project=project_id)


def url(team, path=""):
    return f"/projects/{team.project}{path}"


# ---------- Making ----------

def test_quick_add_from_a_column_numbers_tasks_in_order(app, team):
    client = browser(app, team.member)
    for title in ("First", "Second"):
        response = post(client, url(team, "/tasks/new"), {"quick": "1", "title": title, "status": BACKLOG})
        assert response.status_code == 302
    first, second = get_task(app, team.project, 1), get_task(app, team.project, 2)
    assert (first.title, first.status, second.title) == ("First", BACKLOG, "Second")
    assert b"WEB-2" in client.get(url(team)).data


def test_new_tasks_only_start_in_backlog_or_to_do(app, team):
    post(browser(app, team.manager), url(team, "/tasks/new"), {"quick": "1", "title": "Sneaky", "status": DONE})
    assert get_task(app, team.project, 1).status == TODO


def test_the_full_form(app, team):
    response = post(browser(app, team.manager), url(team, "/tasks/new"), {
        "title": "Login page", "description": "**Bold** plan", "status": TODO, "assignee_id": str(team.member),
        "due_date": "2026-12-01"})
    assert response.status_code == 302
    task = get_task(app, team.project, 1)
    assert task.assignee_id == team.member and str(task.due_date) == "2026-12-01"
    page = browser(app, team.member).get(url(team, "/tasks/1")).data
    assert b"<strong>Bold</strong> plan" in page


def test_a_member_can_only_give_a_new_task_to_themselves(app, team):
    response = post(browser(app, team.member), url(team, "/tasks/new"),
                    {"title": "Mine", "assignee_id": str(team.other)})
    assert response.status_code == 403
    post(browser(app, team.member), url(team, "/tasks/new"), {"title": "Mine", "assignee_id": str(team.member)})
    assert get_task(app, team.project, 1).assignee_id == team.member


def test_viewers_cant_add_tasks(app, team):
    client = browser(app, team.viewer)
    assert post(client, url(team, "/tasks/new"), {"quick": "1", "title": "Nope"}).status_code == 403
    assert b"Add a task" not in client.get(url(team)).data


def test_descriptions_cant_run_scripts(app, team):
    post(browser(app, team.manager), url(team, "/tasks/new"),
         {"title": "Bad", "description": '<script>alert(1)</script> [x](javascript:alert(1))'})
    page = browser(app, team.member).get(url(team, "/tasks/1")).data
    assert b"<script>alert" not in page and b'href="javascript' not in page


# ---------- Editing and deleting ----------

def edit(app, user_id, team, number, **fields):
    form = {"title": "Changed", "description": "", "due_date": "", **fields}
    return post(browser(app, user_id), url(team, f"/tasks/{number}/edit"), form)


def test_who_can_edit(app, team):
    mine = make_task(app, team.project, team.member)
    given = make_task(app, team.project, team.owner, assignee_id=team.member)
    others = make_task(app, team.project, team.owner, assignee_id=team.other)
    assert edit(app, team.member, team, mine).status_code == 302
    assert edit(app, team.member, team, given).status_code == 302
    assert edit(app, team.member, team, others).status_code == 403
    assert edit(app, team.viewer, team, mine).status_code == 403
    assert edit(app, team.manager, team, others).status_code == 302


def test_only_managers_delete(app, team):
    number = make_task(app, team.project, team.member)
    assert post(browser(app, team.member), url(team, f"/tasks/{number}/delete")).status_code == 403
    assert post(browser(app, team.manager), url(team, f"/tasks/{number}/delete")).status_code == 302
    assert get_task(app, team.project, number) is None
    # The history keeps it.
    assert b"deleted" in browser(app, team.owner).get(url(team, "/activity")).data


def test_tasks_in_other_projects_are_404(app, team):
    elsewhere = make_project(app, team.other, "Secret", kind=PERSONAL, key="SEC")
    number = make_task(app, elsewhere, team.other, "Hidden")
    assert browser(app, team.member).get(f"/projects/{elsewhere}/tasks/{number}").status_code == 404


# ---------- Assigning ----------

def test_take_it_and_hand_back(app, team):
    number = make_task(app, team.project, team.owner)
    client = browser(app, team.member)
    assert post(client, url(team, f"/tasks/{number}/assign"), {"action": "take"}).status_code == 302
    assert get_task(app, team.project, number).assignee_id == team.member
    # Someone else can't take it now.
    assert post(browser(app, team.other), url(team, f"/tasks/{number}/assign"), {"action": "take"}).status_code == 403
    post(client, url(team, f"/tasks/{number}/assign"), {"action": "drop"})
    assert get_task(app, team.project, number).assignee_id is None


def test_only_managers_give_tasks_to_others(app, team):
    number = make_task(app, team.project, team.owner)
    assert post(browser(app, team.member), url(team, f"/tasks/{number}/assign"),
                {"assignee_id": str(team.other)}).status_code == 403
    post(browser(app, team.manager), url(team, f"/tasks/{number}/assign"), {"assignee_id": str(team.other)})
    assert get_task(app, team.project, number).assignee_id == team.other
    assert b"gave" in browser(app, team.owner).get(url(team, f"/tasks/{number}")).data


def test_viewers_and_outsiders_cant_be_given_tasks(app, team):
    number = make_task(app, team.project, team.owner)
    outsider = make_user(app, "otto")
    for user_id in (team.viewer, outsider):
        response = post(browser(app, team.manager), url(team, f"/tasks/{number}/assign"), {"assignee_id": str(user_id)})
        assert response.status_code == 400


def test_the_task_page_explains_why_you_cant_move_it(app, team):
    number = make_task(app, team.project, team.owner, assignee_id=team.other)
    page = browser(app, team.member).get(url(team, f"/tasks/{number}")).data
    assert b"Members can only move the tasks given to them" in page
    assert b"Viewers can look and comment" in browser(app, team.viewer).get(url(team, f"/tasks/{number}")).data
