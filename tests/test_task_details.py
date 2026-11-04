"""Labels, priority and checklists."""
from types import SimpleNamespace

import pytest

from planit import db
from planit.models import MANAGER, MEMBER, VIEWER, Label

from .conftest import browser, get_task, make_project, make_task, make_user, post


@pytest.fixture
def team(app):
    owner, manager, member, viewer = (make_user(app, name, name.title()) for name in ("olga", "manny", "mel", "vic"))
    project_id = make_project(app, owner, people={manager: MANAGER, member: MEMBER, viewer: VIEWER})
    return SimpleNamespace(owner=owner, manager=manager, member=member, viewer=viewer, project=project_id)


def labels(app, project_id):
    with app.app_context():
        return {label.name: label.id for label in db.session().query(Label).filter_by(project_id=project_id)}


def url(team, path=""):
    return f"/projects/{team.project}{path}"


# ---------- Labels ----------

def test_new_projects_start_with_three_labels(app, team):
    response = post(browser(app, team.owner), "/projects/new", {"kind": "personal", "name": "Solo", "key": "SOLO"})
    project_id = int(response.location.rsplit("/", 1)[1])
    assert set(labels(app, project_id)) == {"Bug", "Feature", "Design"}


def test_managers_add_rename_and_delete_labels(app, team):
    client = browser(app, team.manager)
    post(client, url(team, "/labels"), {"name": "Urgent fix", "color": "red"})
    label_id = labels(app, team.project)["Urgent fix"]
    post(client, url(team, f"/labels/{label_id}"), {"name": "Hotfix", "color": "orange"})
    assert "Hotfix" in labels(app, team.project)
    post(client, url(team, f"/labels/{label_id}"), {"action": "delete"})
    assert "Hotfix" not in labels(app, team.project)


def test_label_names_are_unique_in_a_project(app, team):
    client = browser(app, team.manager)
    post(client, url(team, "/labels"), {"name": "Bug", "color": "red"})
    post(client, url(team, "/labels"), {"name": "bug", "color": "blue"})
    assert list(labels(app, team.project)) == ["Bug"]


def test_members_cant_change_labels(app, team):
    assert post(browser(app, team.member), url(team, "/labels"), {"name": "Mine"}).status_code == 403


def test_put_labels_and_priority_on_a_task(app, team):
    client = browser(app, team.manager)
    post(client, url(team, "/labels"), {"name": "Design", "color": "purple"})
    design = labels(app, team.project)["Design"]
    post(client, url(team, "/tasks/new"), {"title": "Logo", "priority": "urgent", "label_ids": str(design)})
    page = client.get(url(team)).data
    assert b"Design" in page and b"Urgent" in page
    with app.app_context():
        task = get_task(app, team.project, 1)
        assert task.priority == "urgent"


def test_labels_from_another_project_are_ignored(app, team):
    other = make_project(app, team.manager, "Other", key="OTH")
    post(browser(app, team.manager), f"/projects/{other}/labels", {"name": "Theirs"})
    theirs = labels(app, other)["Theirs"]
    post(browser(app, team.manager), url(team, "/tasks/new"), {"title": "Mine", "label_ids": str(theirs)})
    page = browser(app, team.manager).get(url(team, "/tasks/1")).data
    assert b"Theirs" not in page


def test_urgent_tasks_come_first_in_a_column(app, team):
    make_task(app, team.project, team.owner, "Calm task")
    make_task(app, team.project, team.owner, "Fire!", priority="urgent")
    page = browser(app, team.owner).get(url(team)).data.decode()
    assert page.index("Fire!") < page.index("Calm task")


def test_a_bad_priority_becomes_medium(app, team):
    post(browser(app, team.manager), url(team, "/tasks/new"), {"title": "Odd", "priority": "whenever"})
    assert get_task(app, team.project, 1).priority == "medium"


# ---------- Checklist ----------

def test_add_tick_and_delete_steps(app, team):
    number = make_task(app, team.project, team.member, assignee_id=team.member)
    client = browser(app, team.member)
    for text in ("Draft", "Review"):
        post(client, url(team, f"/tasks/{number}/checklist"), {"text": text})
    with app.app_context():
        task = get_task(app, team.project, number)
        first, second = [item.id for item in task.checklist]
    post(client, url(team, f"/tasks/{number}/checklist/{first}"))
    page = browser(app, team.owner).get(url(team)).data
    assert b"1/2" in page  # the card shows the count
    post(client, url(team, f"/tasks/{number}/checklist/{second}"), {"action": "delete"})
    with app.app_context():
        task = get_task(app, team.project, number)
        assert [(item.text, item.done) for item in task.checklist] == [("Draft", True)]


def test_only_people_who_can_edit_the_task_change_its_steps(app, team):
    number = make_task(app, team.project, team.owner, assignee_id=team.manager)
    post(browser(app, team.owner), url(team, f"/tasks/{number}/checklist"), {"text": "Step"})
    for user_id in (team.member, team.viewer):
        assert post(browser(app, user_id), url(team, f"/tasks/{number}/checklist"), {"text": "Mine"}).status_code == 403


def test_empty_steps_are_refused(app, team):
    number = make_task(app, team.project, team.owner)
    post(browser(app, team.owner), url(team, f"/tasks/{number}/checklist"), {"text": "   "})
    with app.app_context():
        assert get_task(app, team.project, number).checklist == []


def test_steps_of_another_task_are_404(app, team):
    first = make_task(app, team.project, team.owner)
    second = make_task(app, team.project, team.owner)
    post(browser(app, team.owner), url(team, f"/tasks/{first}/checklist"), {"text": "Step"})
    with app.app_context():
        item_id = get_task(app, team.project, first).checklist[0].id
    assert post(browser(app, team.owner), url(team, f"/tasks/{second}/checklist/{item_id}")).status_code == 404
