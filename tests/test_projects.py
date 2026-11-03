"""Projects, their people and Teams, invite links and Project Settings, through the routes."""
import re

import pytest

from planit import db
from planit.models import MANAGER, MEMBER, OWNER, PERSONAL, TEAM, VIEWER, Invite, Project

from .conftest import browser, make_project, make_team, make_user, post, role_of


@pytest.fixture
def people(app):
    """owner, manager, member, viewer, outsider: user ids."""
    return {name: make_user(app, name, name.title()) for name in ("olga", "manny", "mel", "vic", "otto")}


@pytest.fixture
def project_id(app, people):
    return make_project(app, people["olga"], people={people["manny"]: MANAGER, people["mel"]: MEMBER,
                                                    people["vic"]: VIEWER})


def get_project(app, project_id):
    with app.app_context():
        return db.session().get(Project, project_id)


# ---------- Making and seeing projects ----------

def test_make_a_personal_project(app, people):
    client = browser(app, people["olga"])
    response = post(client, "/projects/new", {"kind": "personal", "name": "Learn Flask", "key": ""})
    assert response.status_code == 302
    project = get_project(app, int(re.search(r"/projects/(\d+)", response.location).group(1)))
    assert project.kind == PERSONAL and project.key == "LF" and project.owner_id == people["olga"]


def test_make_a_team_project_with_a_team_and_people(app, people):
    team_id = make_team(app, people["olga"], member_ids=[people["mel"]])
    client = browser(app, people["olga"])
    response = post(client, "/projects/new", {"kind": "team", "name": "Mobile App", "key": "APP",
                                              "team_ids": str(team_id), "usernames": "vic, manny"})
    project_id = int(re.search(r"/projects/(\d+)", response.location).group(1))
    assert get_project(app, project_id).kind == TEAM
    assert role_of(app, people["mel"], project_id) == MEMBER  # through the Team
    assert role_of(app, people["vic"], project_id) == MEMBER
    assert role_of(app, people["otto"], project_id) is None


def test_new_project_form_errors(app, people):
    client = browser(app, people["olga"])
    response = post(client, "/projects/new", {"kind": "team", "name": "", "key": "1x", "usernames": "nobody"})
    assert response.status_code == 400
    assert b"Use 1 to 80" in response.data and b"capital letters" in response.data and b"nobody" in response.data


def test_outsiders_get_404_everywhere(app, people, project_id):
    client = browser(app, people["otto"])
    for url in ("", "/members", "/settings"):
        assert client.get(f"/projects/{project_id}{url}").status_code == 404
    assert b"Website Revamp" not in client.get("/projects").data


def test_everyone_in_it_sees_it_in_their_list(app, people, project_id):
    for name in ("olga", "manny", "mel", "vic"):
        assert b"Website Revamp" in browser(app, people[name]).get("/projects").data


# ---------- People ----------

def test_a_manager_adds_a_member_but_not_a_manager(app, people, project_id):
    client = browser(app, people["manny"])
    assert post(client, f"/projects/{project_id}/members/add", {"username": "otto", "role": MEMBER}).status_code == 302
    assert role_of(app, people["otto"], project_id) == MEMBER
    response = post(client, f"/projects/{project_id}/members/add", {"username": "otto", "role": MANAGER})
    assert response.status_code == 400
    assert role_of(app, people["otto"], project_id) == MEMBER


def test_a_manager_cant_change_another_manager(app, people, project_id):
    other = make_user(app, "mona")
    post(browser(app, people["olga"]), f"/projects/{project_id}/members/add", {"username": "mona", "role": MANAGER})
    response = post(browser(app, people["manny"]), f"/projects/{project_id}/members/{other}", {"action": "remove"})
    assert response.status_code == 403
    assert role_of(app, other, project_id) == MANAGER


def test_the_owner_changes_and_removes_people(app, people, project_id):
    client = browser(app, people["olga"])
    post(client, f"/projects/{project_id}/members/{people['vic']}", {"role": MANAGER})
    assert role_of(app, people["vic"], project_id) == MANAGER
    post(client, f"/projects/{project_id}/members/{people['vic']}", {"action": "remove"})
    assert role_of(app, people["vic"], project_id) is None


@pytest.mark.parametrize("name", ["mel", "vic"])
def test_members_and_viewers_cant_manage_people(app, people, project_id, name):
    client = browser(app, people[name])
    assert post(client, f"/projects/{project_id}/members/add", {"username": "otto", "role": VIEWER}).status_code == 403
    assert post(client, f"/projects/{project_id}/members/{people['vic']}", {"action": "remove"}).status_code == 403
    assert b"Add person" not in client.get(f"/projects/{project_id}/members").data


def test_personal_projects_have_no_members_page(app, people):
    project_id = make_project(app, people["olga"], kind=PERSONAL)
    client = browser(app, people["olga"])
    assert client.get(f"/projects/{project_id}/members").status_code == 302
    assert post(client, f"/projects/{project_id}/members/add", {"username": "otto", "role": MEMBER}).status_code == 403


def test_leave_a_project(app, people, project_id):
    client = browser(app, people["mel"])
    assert post(client, f"/projects/{project_id}/leave").status_code == 302
    assert role_of(app, people["mel"], project_id) is None
    assert post(browser(app, people["olga"]), f"/projects/{project_id}/leave").status_code == 403


# ---------- Teams give and take access ----------

def test_a_team_gives_everyone_in_it_access_and_leaving_takes_it_away(app, people, project_id):
    newcomer = make_user(app, "nina")
    team_id = make_team(app, people["manny"], member_ids=[newcomer])
    client = browser(app, people["manny"])
    assert post(client, f"/projects/{project_id}/teams/add", {"team_id": team_id, "role": MEMBER}).status_code == 302
    assert role_of(app, newcomer, project_id) == MEMBER
    assert browser(app, newcomer).get(f"/projects/{project_id}").status_code == 200
    # Out of the Team, out of the project.
    post(client, f"/teams/{team_id}/members/{newcomer}/remove")
    assert role_of(app, newcomer, project_id) is None
    assert browser(app, newcomer).get(f"/projects/{project_id}").status_code == 404


def test_joining_a_team_later_gives_its_projects(app, people, project_id):
    team_id = make_team(app, people["olga"])
    post(browser(app, people["olga"]), f"/projects/{project_id}/teams/add", {"team_id": team_id, "role": VIEWER})
    post(browser(app, people["olga"]), f"/teams/{team_id}/members", {"username": "otto"})
    assert role_of(app, people["otto"], project_id) == VIEWER


def test_the_highest_of_own_role_and_team_role_wins(app, people, project_id):
    team_id = make_team(app, people["olga"], member_ids=[people["vic"]])
    post(browser(app, people["olga"]), f"/projects/{project_id}/teams/add", {"team_id": team_id, "role": MANAGER})
    assert role_of(app, people["vic"], project_id) == MANAGER  # Viewer alone, Manager through the Team
    post(browser(app, people["olga"]), f"/projects/{project_id}/teams/{team_id}", {"action": "remove"})
    assert role_of(app, people["vic"], project_id) == VIEWER


def test_you_can_only_add_teams_you_are_in(app, people, project_id):
    strangers = make_team(app, people["otto"], "Strangers")
    response = post(browser(app, people["olga"]), f"/projects/{project_id}/teams/add",
                    {"team_id": strangers, "role": MEMBER})
    assert response.status_code == 404


def test_only_the_maker_changes_a_team(app, people):
    team_id = make_team(app, people["olga"], member_ids=[people["mel"]])
    member = browser(app, people["mel"])
    assert member.get(f"/teams/{team_id}").status_code == 200
    assert post(member, f"/teams/{team_id}/members", {"username": "otto"}).status_code == 403
    assert browser(app, people["otto"]).get(f"/teams/{team_id}").status_code == 404
    assert post(member, f"/teams/{team_id}/members/{people['mel']}/remove").status_code == 302  # leaving is fine


def test_make_rename_and_delete_a_team(app, people):
    client = browser(app, people["olga"])
    response = post(client, "/teams", {"name": "Dev Team"})
    team_id = int(response.location.rsplit("/", 1)[1])
    post(client, f"/teams/{team_id}/rename", {"name": "Developers"})
    assert b"Developers" in client.get("/teams").data
    post(client, f"/teams/{team_id}/delete")
    client.get("/teams")  # shows the "was deleted" message once
    assert b"Developers" not in client.get("/teams").data


# ---------- Invite links ----------

def make_link(app, client, project_id, role=MEMBER):
    post(client, f"/projects/{project_id}/invites", {"role": role})
    page = client.get(f"/projects/{project_id}/members").data.decode()
    return re.search(r"http://localhost(/join/[\w-]+)", page).group(1)


def test_an_invite_link_adds_one_person_once(app, people, project_id):
    link = make_link(app, browser(app, people["manny"]), project_id)
    assert link.split("/")[-1] not in str(get_project(app, project_id).id)  # sanity
    with app.app_context():
        stored = db.session().query(Invite).one()
        assert stored.token_hash != link.split("/")[-1]  # only the hash is kept
    otto = browser(app, people["otto"])
    assert b"Join Website Revamp" in otto.get(link).data
    assert post(otto, link).status_code == 302
    assert role_of(app, people["otto"], project_id) == MEMBER
    late = browser(app, make_user(app, "late"))
    assert late.get(link).status_code == 404


def test_the_link_is_shown_only_once(app, people, project_id):
    client = browser(app, people["olga"])
    make_link(app, client, project_id)
    assert b"/join/" not in client.get(f"/projects/{project_id}/members").data


def test_a_manager_cant_make_a_manager_link(app, people, project_id):
    response = post(browser(app, people["manny"]), f"/projects/{project_id}/invites", {"role": MANAGER})
    assert response.status_code == 400


def test_a_cancelled_link_stops_working(app, people, project_id):
    client = browser(app, people["olga"])
    link = make_link(app, client, project_id)
    with app.app_context():
        invite_id = db.session().query(Invite).one().id
    post(client, f"/projects/{project_id}/invites/{invite_id}/cancel")
    assert browser(app, people["otto"]).get(link).status_code == 404


def test_joining_needs_a_login(client):
    response = client.get("/join/whatever")
    assert response.status_code == 302 and "/login" in response.location


# ---------- Project Settings ----------

def test_a_manager_edits_details_but_a_member_cant(app, people, project_id):
    form = {"name": "Site Revamp", "key": "SITE", "color": "teal", "description": "New look", "due_date": "2026-12-31"}
    assert post(browser(app, people["mel"]), f"/projects/{project_id}/settings", form).status_code == 403
    assert post(browser(app, people["manny"]), f"/projects/{project_id}/settings", form).status_code == 302
    project = get_project(app, project_id)
    assert (project.name, project.key, project.color, str(project.due_date)) == ("Site Revamp", "SITE", "teal",
                                                                                 "2026-12-31")


def test_only_the_owner_archives_and_archived_is_read_only(app, people, project_id):
    assert post(browser(app, people["manny"]), f"/projects/{project_id}/archive").status_code == 403
    post(browser(app, people["olga"]), f"/projects/{project_id}/archive")
    assert get_project(app, project_id).is_archived
    manager = browser(app, people["manny"])
    assert manager.get(f"/projects/{project_id}").status_code == 200
    assert post(manager, f"/projects/{project_id}/members/add", {"username": "otto", "role": VIEWER}).status_code == 403
    post(browser(app, people["olga"]), f"/projects/{project_id}/archive")
    assert not get_project(app, project_id).is_archived


def test_transfer_ownership(app, people, project_id):
    assert post(browser(app, people["manny"]), f"/projects/{project_id}/transfer",
                {"user_id": people["mel"]}).status_code == 403
    post(browser(app, people["olga"]), f"/projects/{project_id}/transfer", {"user_id": people["mel"]})
    assert role_of(app, people["mel"], project_id) == OWNER
    assert role_of(app, people["olga"], project_id) == MANAGER


def test_a_team_project_with_people_cant_become_personal(app, people, project_id):
    client = browser(app, people["olga"])
    post(client, f"/projects/{project_id}/kind")
    assert get_project(app, project_id).kind == TEAM
    lonely = make_project(app, people["olga"], "Solo")
    post(client, f"/projects/{lonely}/kind")
    assert get_project(app, lonely).kind == PERSONAL


def test_delete_needs_the_exact_name(app, people, project_id):
    client = browser(app, people["olga"])
    post(client, f"/projects/{project_id}/delete", {"confirm_name": "website revamp"})
    assert get_project(app, project_id) is not None
    assert post(browser(app, people["manny"]), f"/projects/{project_id}/delete",
                {"confirm_name": "Website Revamp"}).status_code == 403
    post(client, f"/projects/{project_id}/delete", {"confirm_name": "Website Revamp"})
    assert get_project(app, project_id) is None
