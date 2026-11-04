"""Search: it finds tasks and projects by name or key, but only in projects you can open."""
from planit.models import MEMBER

from .conftest import browser, make_project, make_task, make_user


def test_search_finds_tasks_and_projects(app):
    olga = make_user(app, "olga")
    project = make_project(app, olga, "Website Revamp")
    make_task(app, project, olga, "Fix the footer links")
    make_task(app, project, olga, "Pick colours")
    page = browser(app, olga).get("/search?q=footer").data
    assert b"Fix the footer links" in page and b"Pick colours" not in page
    assert b"Website Revamp" in browser(app, olga).get("/search?q=revamp").data


def test_search_finds_a_task_by_its_key(app):
    olga = make_user(app, "olga")
    project = make_project(app, olga, key="WEB")
    make_task(app, project, olga, "First")
    make_task(app, project, olga, "Second")
    page = browser(app, olga).get("/search?q=web-2").data
    assert b"Second" in page and b"First" not in page


def test_search_never_shows_other_peoples_projects(app):
    olga, mel, otto = (make_user(app, name) for name in ("olga", "mel", "otto"))
    shared = make_project(app, olga, "Shared", key="SHR", people={mel: MEMBER})
    secret = make_project(app, otto, "Secret plans", key="SEC")
    make_task(app, shared, olga, "Plan the launch")
    make_task(app, secret, otto, "Plan the takeover")
    page = browser(app, mel).get("/search?q=plan").data
    assert b"Plan the launch" in page
    assert b"takeover" not in page and b"Secret plans" not in page
    assert b"takeover" not in browser(app, mel).get("/search?q=SEC-1").data


def test_search_text_is_not_a_pattern(app):
    olga = make_user(app, "olga")
    project = make_project(app, olga)
    make_task(app, project, olga, "Plain title")
    make_task(app, project, olga, "100% done")
    page = browser(app, olga).get("/search?q=%25").data  # a bare %
    assert b"100% done" in page and b"Plain title" not in page


def test_empty_search_lists_your_projects(app):
    olga = make_user(app, "olga")
    make_project(app, olga, "Website Revamp")
    page = browser(app, olga).get("/search").data
    assert b"Website Revamp" in page and b"Nothing Found" not in page
    assert b"Nothing Found" in browser(app, olga).get("/search?q=zzz").data


def test_search_needs_a_login(app):
    assert browser(app).get("/search?q=x").status_code == 302
