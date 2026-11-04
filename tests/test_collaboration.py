"""Comments, @mentions and the Inbox."""
from types import SimpleNamespace

import pytest

from planit import db
from planit.models import MANAGER, MEMBER, VIEWER, Notification

from .conftest import browser, make_project, make_task, make_user, post


@pytest.fixture
def team(app):
    owner, manager, member, viewer, outsider = (make_user(app, name, name.title())
                                                for name in ("olga", "manny", "mel", "vic", "otto"))
    project_id = make_project(app, owner, people={manager: MANAGER, member: MEMBER, viewer: VIEWER})
    return SimpleNamespace(owner=owner, manager=manager, member=member, viewer=viewer, outsider=outsider,
                           project=project_id)


def notes(app, user_id):
    with app.app_context():
        return [note.kind for note in db.session().query(Notification).filter_by(user_id=user_id)
                .order_by(Notification.id)]


def comment(app, user_id, team, number, body):
    return post(browser(app, user_id), f"/projects/{team.project}/tasks/{number}/comments", {"body": body})


# ---------- Comments ----------

def test_viewers_can_comment(app, team):
    number = make_task(app, team.project, team.owner)
    assert comment(app, team.viewer, team, number, "Looks great").status_code == 302
    page = browser(app, team.owner).get(f"/projects/{team.project}/tasks/{number}").data
    assert b"Looks great" in page and b"commented on" in page


def test_comments_are_plain_text(app, team):
    number = make_task(app, team.project, team.owner)
    comment(app, team.member, team, number, "<b>bold</b> **not markdown**")
    page = browser(app, team.owner).get(f"/projects/{team.project}/tasks/{number}").data
    assert b"&lt;b&gt;bold&lt;/b&gt; **not markdown**" in page


def test_empty_comments_are_refused(app, team):
    number = make_task(app, team.project, team.owner)
    comment(app, team.member, team, number, "   ")
    assert b"comment-body" not in browser(app, team.owner).get(f"/projects/{team.project}/tasks/{number}").data


def test_outsiders_cant_comment(app, team):
    number = make_task(app, team.project, team.owner)
    assert comment(app, team.outsider, team, number, "Hi").status_code == 404


def comment_id(app):
    from planit.models import Comment

    with app.app_context():
        return db.session().query(Comment).order_by(Comment.id.desc()).first().id


def test_only_the_writer_edits_and_managers_can_delete(app, team):
    number = make_task(app, team.project, team.owner)
    comment(app, team.member, team, number, "First words")
    cid = comment_id(app)
    url = f"/projects/{team.project}/tasks/{number}/comments/{cid}"
    assert post(browser(app, team.viewer), url, {"body": "Hacked"}).status_code == 403
    assert post(browser(app, team.member), url, {"body": "Better words"}).status_code == 302
    page = browser(app, team.owner).get(f"/projects/{team.project}/tasks/{number}").data
    assert b"Better words" in page and b"(edited)" in page
    assert post(browser(app, team.viewer), url, {"action": "delete"}).status_code == 403
    assert post(browser(app, team.manager), url, {"action": "delete"}).status_code == 302
    assert b"Better words" not in browser(app, team.owner).get(f"/projects/{team.project}/tasks/{number}").data


# ---------- Mentions ----------

def test_a_mention_reaches_the_inbox_and_is_highlighted(app, team):
    number = make_task(app, team.project, team.owner)
    comment(app, team.member, team, number, "What do you think, @vic? And @otto?")
    assert notes(app, team.viewer) == ["mentioned"]
    assert notes(app, team.outsider) == []  # not in the project: no notification, no highlight
    page = browser(app, team.owner).get(f"/projects/{team.project}/tasks/{number}").data
    assert b'class="mention"' in page and b">@vic<" in page and b">@otto<" not in page
    inbox = browser(app, team.viewer).get("/inbox").data
    assert b"mentioned you on" in inbox and b"What do you think" in inbox


def test_the_task_owner_hears_about_comments_but_not_twice(app, team):
    number = make_task(app, team.project, team.owner, assignee_id=team.member)
    comment(app, team.viewer, team, number, "Hello @mel")
    assert notes(app, team.member) == ["mentioned"]  # mentioned, so no extra "commented"
    assert notes(app, team.owner) == ["commented"]   # the reporter
    comment(app, team.member, team, number, "Thanks")
    assert notes(app, team.member) == ["mentioned"]  # nobody hears about their own comment


# ---------- Notifications from the workflow ----------

def test_review_approve_and_assign_notify_the_right_people(app, team):
    number = make_task(app, team.project, team.owner, assignee_id=team.member)
    base = f"/projects/{team.project}/tasks/{number}"
    post(browser(app, team.manager), f"{base}/assign", {"assignee_id": str(team.member)})  # no change, no note
    for to in ("in_progress", "review"):
        post(browser(app, team.member), f"{base}/move", {"to": to})
    assert notes(app, team.owner) == ["review"] and notes(app, team.manager) == ["review"]
    post(browser(app, team.manager), f"{base}/move", {"to": "done"})
    assert notes(app, team.member) == ["approved"]
    other = make_task(app, team.project, team.owner)
    post(browser(app, team.manager), f"/projects/{team.project}/tasks/{other}/assign",
         {"assignee_id": str(team.member)})
    assert notes(app, team.member) == ["approved", "assigned"]


def test_being_added_to_a_project_is_in_the_inbox(app, team):
    post(browser(app, team.owner), f"/projects/{team.project}/members/add", {"username": "otto", "role": MEMBER})
    assert notes(app, team.outsider) == ["added"]


# ---------- The Inbox ----------

def test_opening_a_note_marks_it_read_and_goes_to_the_task(app, team):
    number = make_task(app, team.project, team.owner)
    comment(app, team.member, team, number, "@vic look")
    client = browser(app, team.viewer)
    assert b'class="count"' in client.get("/").data  # the sidebar shows it
    with app.app_context():
        note = db.session().query(Notification).filter_by(user_id=team.viewer).one()
    response = client.get(f"/inbox/{note.id}")
    assert f"/projects/{team.project}/tasks/{number}#comment-" in response.location
    assert b'class="count"' not in client.get("/").data


def test_others_cant_open_your_notes(app, team):
    number = make_task(app, team.project, team.owner)
    comment(app, team.member, team, number, "@vic look")
    with app.app_context():
        note_id = db.session().query(Notification).filter_by(user_id=team.viewer).one().id
    assert browser(app, team.member).get(f"/inbox/{note_id}").status_code == 404


def test_mark_all_read(app, team):
    number = make_task(app, team.project, team.owner)
    comment(app, team.member, team, number, "@vic one")
    comment(app, team.member, team, number, "@vic two")
    client = browser(app, team.viewer)
    assert b"2 new things need you" in client.get("/inbox").data
    post(client, "/inbox/read")
    assert b"all caught up" in client.get("/inbox").data
