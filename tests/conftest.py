import os

import pytest
from sqlalchemy import select

from planit import auth, create_app, db, permissions
from planit.models import TEAM, Project, ProjectMember, ProjectTeam, Team, User

# Tests use a fresh SQLite file per test. To check everything on PostgreSQL
# too, set TEST_DATABASE_URL to an EMPTY Neon branch (its tables are dropped
# and made again for every test, so never point it at the live database).
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

CSRF = "test-csrf-token"
PASSWORD = "correct horse"


@pytest.fixture
def app(tmp_path):
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "test",
        "DATABASE": str(tmp_path / "test.sqlite"),
        "DATABASE_URL": TEST_DATABASE_URL,
    })
    with app.app_context():
        if TEST_DATABASE_URL:
            db.drop_tables()
        db.create_tables()
    return app


@pytest.fixture
def ctx(app):
    """An app context, for tests that use db.session() directly."""
    with app.app_context():
        yield db.session()


@pytest.fixture
def client(app):
    client = app.test_client()
    # Every POST needs the session's CSRF token. Put a known one in the session.
    with client.session_transaction() as session:
        session["csrf"] = CSRF
    return client


def post(client, url, data=None, **kwargs):
    """POST a form with the right CSRF token, like a real page would."""
    # Logging in or out starts a new session (and a new token), so set it every time.
    with client.session_transaction() as session:
        session["csrf"] = CSRF
    return client.post(url, data={"csrf_token": CSRF, **(data or {})}, **kwargs)


def make_user(app, username, display_name=None, **fields):
    """Put a user straight into the database. Returns the id."""
    with app.app_context():
        s = db.session()
        user = auth.create_user(s, username, PASSWORD, display_name=display_name)
        for name, value in fields.items():
            setattr(user, name, value)
        s.commit()
        return user.id


def log_in_as(client, user_id):
    """Skip the login form: put the user straight into the session."""
    with client.application.app_context():
        version = db.session().get(User, user_id).session_version
    with client.session_transaction() as session:
        session["user_id"] = user_id
        session["session_version"] = version
        session["csrf"] = CSRF
    return client


def browser(app, user_id=None):
    """A fresh client, logged in as this user if given."""
    client = app.test_client()
    with client.session_transaction() as session:
        session["csrf"] = CSRF
    return log_in_as(client, user_id) if user_id else client


def is_logged_in(client):
    """The real check: load_user() runs on every request and drops a session that
    is no longer valid, so ask after a request what is left in the cookie."""
    client.get("/settings")
    with client.session_transaction() as session:
        return "user_id" in session


def get_user(app, username):
    with app.app_context():
        return db.session().scalar(select(User).where(User.username == username))


def make_project(app, owner_id, name="Website Revamp", kind=TEAM, people=None, teams=None, **fields):
    """A project with people ({user_id: role}) and Teams ({team_id: role}). Returns the id."""
    with app.app_context():
        s = db.session()
        project = Project(name=name, key=fields.pop("key", "WEB"), kind=kind, owner_id=owner_id, **fields)
        s.add(project)
        s.flush()
        for user_id, role in (people or {}).items():
            s.add(ProjectMember(project_id=project.id, user_id=user_id, role=role))
        for team_id, role in (teams or {}).items():
            s.add(ProjectTeam(project_id=project.id, team_id=team_id, role=role))
        s.commit()
        return project.id


def make_team(app, creator_id, name="Design Team", member_ids=()):
    """A Team made by creator_id, with them and member_ids in it. Returns the id."""
    with app.app_context():
        s = db.session()
        team = Team(name=name, created_by_id=creator_id)
        team.members = [s.get(User, user_id) for user_id in (creator_id, *member_ids)]
        s.add(team)
        s.commit()
        return team.id


def role_of(app, user_id, project_id):
    with app.app_context():
        s = db.session()
        return permissions.stored_role(s, s.get(User, user_id), s.get(Project, project_id))
