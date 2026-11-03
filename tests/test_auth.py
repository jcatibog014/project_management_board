"""Signing up, logging in, recovery codes, Settings, and the form protection."""
import re

import pytest

from planit import auth, db
from planit.dates import utcnow

from .conftest import CSRF, PASSWORD, browser, get_user, is_logged_in, log_in_as, make_user, post

CODE = re.compile(rb"[A-Z2-9]{4}-[A-Z2-9]{4}-[A-Z2-9]{4}-[A-Z2-9]{4}")


def sign_up(client, username="ana", password="long enough", confirm=None, **extra):
    return post(client, "/signup", {"username": username, "password": password,
                                    "confirm_password": password if confirm is None else confirm, **extra})


# ---------- Sign up ----------

def test_sign_up_logs_in_and_shows_a_recovery_code_once(app, client):
    response = sign_up(client, "Ana", display_name="Ana Cruz")
    assert response.status_code == 302 and "/recovery-code" in response.location
    page = client.get(response.location).data
    assert CODE.search(page)
    assert is_logged_in(client)
    # A reload shows nothing: the code exists only once.
    assert client.get("/recovery-code").status_code == 302
    user = get_user(app, "ana")
    assert user.display_name == "Ana Cruz" and user.recovery_hash


@pytest.mark.parametrize("username, problem", [
    ("ab", b"Use 3 to 40"), ("has space", b"Use only letters"), ("admin", b"not available"),
    ("demo-123", b"not available"),
])
def test_sign_up_refuses_bad_usernames(client, username, problem):
    response = sign_up(client, username)
    assert response.status_code == 400 and problem in response.data


def test_sign_up_refuses_a_short_or_mismatched_password(client):
    assert b"at least 8" in sign_up(client, password="short").data
    assert b"not the same" in sign_up(client, confirm="different!").data


def test_sign_up_refuses_a_taken_username(app, client):
    make_user(app, "ana")
    response = sign_up(client, "ANA")
    assert response.status_code == 400 and b"already taken" in response.data


def test_robots_that_fill_the_hidden_field_are_ignored(app, client):
    sign_up(client, website="spam.example")
    assert get_user(app, "ana") is None


# ---------- Log in and out ----------

def test_log_in_and_out(app, client):
    make_user(app, "ana")
    response = post(client, "/login", {"username": "Ana", "password": PASSWORD, "next": "/settings"})
    assert response.status_code == 302 and response.location == "/settings"
    assert is_logged_in(client)
    post(client, "/logout")
    assert not is_logged_in(client)


def test_a_wrong_password_never_says_whether_the_user_exists(app, client):
    make_user(app, "ana")
    wrong_password = post(client, "/login", {"username": "ana", "password": "nope"})
    no_such_user = post(client, "/login", {"username": "nobody", "password": "nope"})
    assert wrong_password.status_code == no_such_user.status_code == 401
    assert b"Wrong username or password" in wrong_password.data and b"Wrong username or password" in no_such_user.data


def test_five_wrong_passwords_lock_the_account(app, client):
    make_user(app, "ana")
    for _ in range(auth.MAX_FAILED_LOGINS):
        post(client, "/login", {"username": "ana", "password": "nope"})
    response = post(client, "/login", {"username": "ana", "password": PASSWORD})
    assert b"wait 15 minutes" in response.data
    assert get_user(app, "ana").locked_until > utcnow()


@pytest.mark.parametrize("target", ["https://evil.example", "//evil.example", "/\\evil.example", "/\nx"])
def test_log_in_never_sends_people_to_another_site(app, client, target):
    make_user(app, "ana")
    response = post(client, "/login", {"username": "ana", "password": PASSWORD, "next": target})
    assert response.location == "/"


def test_pages_need_a_login(client):
    response = client.get("/settings")
    assert response.status_code == 302 and "/login?next=/settings" in response.location


# ---------- Recovery code ----------

def recovery_code_for(app, username):
    with app.app_context():
        s = db.session()
        user = auth.find_user(s, username)
        code = auth.new_recovery_code(user)
        s.commit()
        return code


def test_the_recovery_code_sets_a_new_password_and_is_replaced(app, client):
    make_user(app, "ana")
    code = recovery_code_for(app, "ana")
    response = post(client, "/forgot", {"username": "ana", "code": code.lower().replace("-", " "),
                                        "new_password": "brand new pass", "confirm_password": "brand new pass"})
    assert response.status_code == 302
    assert CODE.search(client.get(response.location).data)  # the next code
    post(client, "/logout")
    assert post(client, "/login", {"username": "ana", "password": "brand new pass"}).status_code == 302
    # The old code worked once only.
    post(client, "/logout")
    again = post(client, "/forgot", {"username": "ana", "code": code, "new_password": "another one",
                                     "confirm_password": "another one"})
    assert again.status_code == 400 and b"Wrong username or recovery code" in again.data


def test_wrong_recovery_codes_lock_the_account_too(app, client):
    make_user(app, "ana")
    recovery_code_for(app, "ana")
    for _ in range(auth.MAX_FAILED_LOGINS):
        post(client, "/forgot", {"username": "ana", "code": "AAAA-AAAA-AAAA-AAAA",
                                 "new_password": "brand new pass", "confirm_password": "brand new pass"})
    assert get_user(app, "ana").locked_until > utcnow()


# ---------- Settings ----------

def test_change_name(app):
    client = browser(app, make_user(app, "ana"))
    assert post(client, "/settings", {"action": "name", "display_name": "Ana C."}).status_code == 302
    assert get_user(app, "ana").display_name == "Ana C."


def test_changing_the_password_logs_out_other_devices(app):
    user_id = make_user(app, "ana")
    phone, laptop = browser(app, user_id), browser(app, user_id)
    response = post(laptop, "/settings", {"action": "password", "current_password": PASSWORD,
                                          "new_password": "brand new pass", "confirm_password": "brand new pass"})
    assert response.status_code == 302
    assert is_logged_in(laptop) and not is_logged_in(phone)


def test_a_new_recovery_code_needs_the_password(app):
    client = browser(app, make_user(app, "ana"))
    wrong = post(client, "/settings", {"action": "recovery", "current_password": "nope"})
    assert wrong.status_code == 400
    right = post(client, "/settings", {"action": "recovery", "current_password": PASSWORD})
    assert CODE.search(client.get(right.location).data)


# ---------- Forms and headers ----------

def test_a_form_without_the_csrf_token_is_refused(app, client):
    make_user(app, "ana")
    response = client.post("/login", data={"username": "ana", "password": PASSWORD, "csrf_token": "wrong"})
    assert response.status_code == 400 and b"expired" in response.data


def test_every_page_sends_the_security_headers(client):
    response = client.get("/login")
    assert "script-src 'self'" in response.headers["Content-Security-Policy"]
    assert response.headers["X-Frame-Options"] == "DENY"


def test_health_check(client):
    assert client.get("/healthz").data == b"ok"


def test_the_login_and_home_pages_draw(app, client):
    assert b"Your projects, in orbit." in client.get("/login").data
    log_in_as(client, make_user(app, "ana", "Ana"))
    assert b"Hello, Ana" in client.get("/").data
    assert CSRF  # the session's token is the one the test set
