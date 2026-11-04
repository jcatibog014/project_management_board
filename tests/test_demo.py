"""The demo: each visitor gets their own sample company, which can never touch
or reach the real site, with an example on every page it can open."""
import re
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from planit import auth, db
from planit.dates import utcnow
from planit.models import MEMBER, OWNER, Project, Task, Team, User

from .conftest import CSRF, browser, get_user, make_project, make_user, post, role_of


def start_demo(app):
    client = app.test_client()
    with client.session_transaction() as session:
        session["csrf"] = CSRF
    assert post(client, "/demo").status_code == 302
    return client


def demo_user(client):
    with client.session_transaction() as session:
        user_id = session["user_id"]
    with client.application.app_context():
        return db.session().get(User, user_id)


def demo_projects(app, user):
    with app.app_context():
        s = db.session()
        from planit import projects
        return {project.name: project.id for project in projects.visible(s, user)}


def count(app, model, *where):
    with app.app_context():
        return db.session().scalar(select(func.count()).select_from(model).where(*where))


@pytest.fixture
def demo(app):
    return start_demo(app)


# ---------- Starting it ----------

def test_try_demo_makes_sam_with_a_sample_company(app, demo):
    user = demo_user(demo)
    assert user.is_demo and user.display_name == "Sam Rivera" and user.demo_expires_at > utcnow()
    assert set(demo_projects(app, user)) == {"Website Revamp", "Mobile App Launch", "Marketing Plan", "Learn Flask"}
    page = demo.get("/").data
    assert b"Good" in page and b"Sam" in page and b"sample company" in page


def test_the_visitor_plays_a_different_role_in_each_project(app, demo):
    user = demo_user(demo)
    ids = demo_projects(app, user)
    assert role_of(app, user.id, ids["Website Revamp"]) == OWNER
    assert role_of(app, user.id, ids["Mobile App Launch"]) == MEMBER  # through the Dev Team
    assert role_of(app, user.id, ids["Marketing Plan"]) == "viewer"


def test_two_visitors_get_two_separate_companies(app):
    first, second = start_demo(app), start_demo(app)
    one, two = demo_user(first), demo_user(second)
    assert one.id != two.id
    assert set(demo_projects(app, one).values()).isdisjoint(demo_projects(app, two).values())
    web = demo_projects(app, one)["Website Revamp"]
    assert second.get(f"/projects/{web}").status_code == 404


def test_the_demo_cant_log_in_with_the_form(app, demo):
    user = demo_user(demo)
    with app.app_context():
        assert auth.find_user(db.session(), user.username) is None


# ---------- Every page has an example ----------

EMPTY_PAGE_SIGNS = [b"empty-state", b"No comments yet", b"No Teams share", b"Nothing Has Happened Yet"]


def demo_pages(app, user):
    ids = demo_projects(app, user)
    pages = ["/", "/my-tasks", "/calendar", "/calendar?week=", "/inbox", "/inbox?show=reviews", "/projects", "/teams",
             "/settings", "/search", "/search?q=logo"]
    for project_id in ids.values():
        pages += [f"/projects/{project_id}{tab}" for tab in ("", "/list", "/dashboard", "/activity", "/settings")]
    with app.app_context():
        s = db.session()
        for team_id in s.scalars(select(Team.id).join(Team.members).where(User.id == user.id)):
            pages.append(f"/teams/{team_id}")
    pages += [f"/projects/{ids[name]}/members" for name in ("Website Revamp", "Mobile App Launch", "Marketing Plan")]
    pages.append(f"/projects/{ids['Website Revamp']}/tasks/5")
    return pages


def test_no_page_the_demo_can_open_is_empty(app, demo):
    for url in demo_pages(app, demo_user(demo)):
        response = demo.get(url)
        assert response.status_code == 200, url
        for sign in EMPTY_PAGE_SIGNS:
            assert sign not in response.data, (url, sign)


def test_every_board_column_has_a_card_somewhere(app, demo):
    ids = demo_projects(app, demo_user(demo))
    page = demo.get(f"/projects/{ids['Website Revamp']}").data.decode()
    for column in ("backlog", "todo", "in_progress", "review", "done"):
        section = page.split(f'id="column-{column}"')[1].split("</section>")[0]
        assert 'class="task-card' in section, column


def test_the_calendar_has_tasks_this_month_and_the_inbox_has_new_lines(app, demo):
    assert b'class="cal-task' in demo.get("/calendar").data
    assert b"is-unread" in demo.get("/inbox").data
    assert b"@sam" in demo.get("/inbox").data


def test_the_dashboard_has_finished_work_to_chart(app, demo):
    ids = demo_projects(app, demo_user(demo))
    page = demo.get(f"/projects/{ids['Website Revamp']}/dashboard").data
    assert b'class="bar-done"' in page


# ---------- View As ----------

def test_view_as_changes_what_the_demo_may_do(app, demo):
    ids = demo_projects(app, demo_user(demo))
    web = ids["Website Revamp"]
    assert b"New task" in demo.get(f"/projects/{web}").data
    post(demo, "/demo/view-as", {"role": "viewer"})
    board = demo.get(f"/projects/{web}").data
    assert b"New task" not in board and b"look and comment" in board
    assert post(demo, f"/projects/{web}/tasks/new", {"quick": "1", "title": "Nope"}).status_code == 403
    post(demo, "/demo/view-as", {"role": ""})
    assert b"New task" in demo.get(f"/projects/{web}").data


def test_view_as_never_makes_the_demo_an_owner(app, demo):
    ids = demo_projects(app, demo_user(demo))
    post(demo, "/demo/view-as", {"role": "manager"})
    marketing = ids["Marketing Plan"]  # the demo is only a Viewer here, and doesn't own it
    assert post(demo, f"/projects/{marketing}/archive").status_code == 403
    post(demo, "/demo/view-as", {"role": "owner"})  # not a choice: ignored
    with demo.session_transaction() as session:
        assert "view_as" not in session


def test_view_as_leaves_personal_projects_alone(app, demo):
    ids = demo_projects(app, demo_user(demo))
    post(demo, "/demo/view-as", {"role": "viewer"})
    assert b"New task" in demo.get(f"/projects/{ids['Learn Flask']}").data


def test_view_as_is_only_for_the_demo(app):
    client = browser(app, make_user(app, "ana"))
    assert post(client, "/demo/view-as", {"role": "viewer"}).status_code == 403


# ---------- Never reaching the real site ----------

def test_the_demo_only_finds_its_own_teammates(app, demo):
    real = make_user(app, "ana")  # a real person with the same name as a sample teammate
    ids = demo_projects(app, demo_user(demo))
    web = ids["Website Revamp"]
    post(demo, f"/projects/{web}/members/add", {"username": "ana", "role": "manager"})
    assert role_of(app, real, web) is None  # the sample Ana was found, not the real one


def test_real_people_never_find_demo_users(app, demo):
    user = demo_user(demo)
    owner = make_user(app, "olga")
    project_id = make_project(app, owner)
    post(browser(app, owner), f"/projects/{project_id}/members/add", {"username": user.username, "role": MEMBER})
    assert role_of(app, user.id, project_id) is None


def test_the_demo_cant_make_invite_links_or_change_its_account(app, demo):
    ids = demo_projects(app, demo_user(demo))
    assert post(demo, f"/projects/{ids['Website Revamp']}/invites", {"role": MEMBER}).status_code == 403
    assert post(demo, "/settings", {"action": "name", "display_name": "Hacker"}).status_code == 403


# ---------- Cleaning up ----------

def test_old_demos_are_deleted_with_everything_in_them(app):
    old = start_demo(app)
    user = demo_user(old)
    with app.app_context():
        s = db.session()
        s.execute(User.__table__.update().where(User.username.like(f"demo-{user.username.split('-')[1]}-%"))
                  .values(demo_expires_at=utcnow() - timedelta(minutes=1)))
        s.commit()
    assert not re.search(rb"Sam", old.get("/").data or b"")  # the cookie stops working at once
    start_demo(app)  # starting a new demo clears the old ones
    assert get_user(app, user.username) is None
    assert count(app, Project) == 4  # only the new demo's projects are left
    assert count(app, User, User.is_demo.is_(True)) == 6  # just the new visitor and their five teammates
    assert count(app, Task) > 0


def test_too_many_demos_at_once_are_refused(app, monkeypatch):
    monkeypatch.setattr(auth, "MAX_DEMOS", 1)
    start_demo(app)
    client = app.test_client()
    with client.session_transaction() as session:
        session["csrf"] = CSRF
    response = post(client, "/demo")
    assert "/login" in response.location
    assert count(app, User, User.username.like("demo-%-sam")) == 1


def test_purge_demos_command(app):
    start_demo(app)
    result = app.test_cli_runner().invoke(args=["purge-demos"])
    assert result.exit_code == 0 and "Deleted 0" in result.output
