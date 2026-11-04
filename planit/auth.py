"""Logging in and out, signing up, recovery codes, and protection for every form.

Anyone can sign up. What a user may do in a project is never a property of
the account: it comes from the project's people and Teams (permissions.py).

Passwords are stored only as hashes. The login cookie holds the user's id
and their session_version; load_user() checks both on every request, so an
old cookie (after a password change) is logged out straight away.

There is no email. At sign-up everyone gets a recovery code, shown once,
that can set a new password on the Forgot Password page.
"""
import functools
import hmac
import re
import secrets
from datetime import timedelta

import click
from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for
from flask.cli import with_appcontext
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from . import db
from .dates import utcnow
from .models import User

bp = Blueprint("auth", __name__)

USERNAME_MIN_LENGTH = 3
USERNAME_MAX_LENGTH = 40
DISPLAY_NAME_MAX_LENGTH = 60
PASSWORD_MIN_LENGTH = 8
USERNAME_PATTERN = re.compile(r"[a-z0-9_-]+")
# Nobody may sign up with a name that looks like it speaks for the site.
RESERVED_USERNAMES = {"admin", "administrator", "owner", "planit", "plan-it", "support", "system"}
# After 5 wrong passwords (or recovery codes) in a row, the account waits 15 minutes.
MAX_FAILED_LOGINS = 5
LOCK_TIME = timedelta(minutes=15)
# No 0/O or 1/I/L, so a code copied by hand is read back the same.
RECOVERY_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

WRONG_LOGIN = "Wrong username or password."
WRONG_RECOVERY = "Wrong username or recovery code."
LOCKED = "Too many failed attempts. Please wait 15 minutes and try again."

# Every visitor who presses Try Demo gets their own sample company, deleted after a day.
DEMO_LIFETIME = timedelta(hours=24)
# What the demo's View As can play in its team projects. Owning stays real:
# only the actual owner can archive, delete or transfer.
VIEW_AS_ROLES = ("manager", "member", "viewer")


# ---------- Users in the database ----------

def clean_username(text):
    return (text or "").strip().lower()


def username_problem(username):
    """Why this (cleaned) username can't be used, or None if it is fine."""
    if not USERNAME_MIN_LENGTH <= len(username) <= USERNAME_MAX_LENGTH:
        return f"Use {USERNAME_MIN_LENGTH} to {USERNAME_MAX_LENGTH} characters."
    if not USERNAME_PATTERN.fullmatch(username):
        return "Use only letters, numbers, - and _."
    if username in RESERVED_USERNAMES or username.startswith("demo"):
        return "That username is not available."
    return None


def password_problem(password, confirm):
    if len(password) < PASSWORD_MIN_LENGTH:
        return f"Use at least {PASSWORD_MIN_LENGTH} characters."
    if password != confirm:
        return "The two passwords are not the same."
    return None


def find_user(s, username):
    """A real (not demo) user by username, or None."""
    return s.scalar(select(User).where(User.username == clean_username(username), User.is_demo.is_(False)))


def create_user(s, username, password, display_name=None, is_demo=False):
    """Add a user. The caller commits."""
    username = clean_username(username)
    user = User(username=username, display_name=display_name or username,
                password_hash=generate_password_hash(password), is_demo=is_demo)
    s.add(user)
    s.flush()
    return user


def set_password(user, password):
    user.password_hash = generate_password_hash(password)
    user.failed_logins = 0
    user.locked_until = None
    user.session_version += 1  # every other device is logged out


def new_recovery_code(user):
    """Give the user a fresh code and return it. This is the only time it
    exists in the clear: the old code stops working."""
    code = "-".join("".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(4)) for _ in range(4))
    user.recovery_hash = generate_password_hash(code)
    return code


def clean_recovery_code(text):
    """People type codes in any case and with or without dashes."""
    letters = re.sub(r"[^A-Z0-9]", "", (text or "").upper())
    return "-".join(letters[i:i + 4] for i in range(0, len(letters), 4))


def _failed(s, user, moment):
    user.failed_logins += 1
    if user.failed_logins >= MAX_FAILED_LOGINS:
        user.failed_logins, user.locked_until = 0, moment + LOCK_TIME
    s.commit()


def check_login(s, username, password, moment):
    """Return (user, None) if the password is right, else (None, message).
    The message never says whether the username exists."""
    user = find_user(s, username)
    if user is None:
        return None, WRONG_LOGIN
    if user.locked_until and user.locked_until > moment:
        return None, LOCKED
    if not check_password_hash(user.password_hash, password or ""):
        _failed(s, user, moment)
        return None, WRONG_LOGIN
    user.failed_logins, user.locked_until = 0, None
    s.commit()
    return user, None


def check_recovery(s, username, code, moment):
    """Like check_login, but with the recovery code. Wrong codes count towards
    the same lock, so the code can't be guessed either."""
    user = find_user(s, username)
    if user is None or user.recovery_hash is None:
        return None, WRONG_RECOVERY
    if user.locked_until and user.locked_until > moment:
        return None, LOCKED
    if not check_password_hash(user.recovery_hash, clean_recovery_code(code)):
        _failed(s, user, moment)
        return None, WRONG_RECOVERY
    return user, None


def purge_demos(s, moment):
    """Delete every demo that has run out, with everything in it. The database
    does the rest: projects, tasks and Teams are deleted with their owner."""
    gone = s.execute(delete(User).where(User.is_demo.is_(True), User.demo_expires_at <= moment))
    return gone.rowcount


def start_demo(s, moment):
    """A fresh demo visitor ("Sam Rivera") and their sample company. The caller commits."""
    from . import seed

    purge_demos(s, moment)
    tag = secrets.token_hex(4)
    # Nobody knows this password: a demo is only opened with the button (and
    # find_user() never finds demo users, so the login form can't open one).
    user = create_user(s, f"demo-{tag}-sam", secrets.token_urlsafe(32), display_name="Sam Rivera", is_demo=True)
    user.demo_expires_at = moment + DEMO_LIFETIME
    seed.build(s, user, moment)
    return user


def safe_next(target, default=None):
    """Only go back to a page on this site (after logging in or saving a form).

    "/projects/3" is fine. "https://evil.example" and "//evil.example"
    are not: a fake link could send people there after a real login. Browsers
    drop tabs and newlines and read a backslash as a slash, so those are out too.
    """
    if (target and target.startswith("/") and not target.startswith("//")
            and "\\" not in target and not any(ord(c) < 32 for c in target)):
        return target
    return default or url_for("main.home")


def log_in(user):
    session.clear()  # a new session for the new user (old cookies can't be reused)
    session.permanent = True  # stay logged in for PERMANENT_SESSION_LIFETIME
    session["user_id"] = user.id
    session["session_version"] = user.session_version


def show_recovery_code(code):
    """The next page shows the code once (recovery_code() below)."""
    session["recovery_code"] = code


# ---------- Every request ----------

@bp.before_app_request
def load_user():
    g.user = None
    user_id = session.get("user_id")
    if user_id is None:
        return
    user = db.session().get(User, user_id)
    if (user is None or session.get("session_version") != user.session_version
            or (user.is_demo and user.demo_expires_at and user.demo_expires_at <= utcnow())):
        # Keep the CSRF token: only the login part of this cookie is out of date.
        session.pop("user_id", None)
        session.pop("session_version", None)
        return
    g.user = user
    # The demo's View As choice (permissions.effective_role uses it).
    if user.is_demo and session.get("view_as") in VIEW_AS_ROLES:
        g.view_as = session["view_as"]


def csrf_token():
    """A secret per session, put into every form as a hidden field.

    Another website could make your browser send a form to this site (your
    login cookie goes with it). It can't read this secret, so its form fails.
    """
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


@bp.before_app_request
def check_csrf():
    if request.method != "POST":
        return
    sent = request.form.get("csrf_token", "") or request.headers.get("X-CSRF-Token", "")
    expected = session.get("csrf", "")
    # compare_digest takes the same time for every wrong guess.
    if not expected or not hmac.compare_digest(sent, expected):
        abort(400, "This form has expired. Please go back, reload the page and try again.")


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            # Only a GET can be repeated after logging in.
            next_page = request.full_path.rstrip("?") if request.method == "GET" else None
            return redirect(url_for("auth.login", next=next_page))
        return view(*args, **kwargs)
    return wrapped


def not_demo(message="The demo can't change this. Sign up to make it your own."):
    if g.user is not None and g.user.is_demo:
        abort(403, message)


# ---------- Pages ----------

@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user is not None:
        return redirect(url_for("main.home"))
    next_page = request.values.get("next", "")
    error = None
    username = ""
    if request.method == "POST":
        username = request.form.get("username", "")[:USERNAME_MAX_LENGTH]
        user, error = check_login(db.session(), username, request.form.get("password", ""), utcnow())
        if user:
            log_in(user)
            return redirect(safe_next(next_page))
    status = 401 if error else 200
    return render_template("login.html", error=error, username=username, next=next_page), status


@bp.post("/demo")
def demo():
    s = db.session()
    user = start_demo(s, utcnow())
    s.commit()
    log_in(user)
    flash("Welcome to the demo! You are Sam Rivera at Orbit Labs. Try every role with View As in the menu.")
    return redirect(url_for("main.home"))


@bp.post("/demo/view-as")
@login_required
def view_as():
    if not g.user.is_demo:
        abort(403, "View As is only for the demo.")
    role = request.form.get("role", "")
    if role in VIEW_AS_ROLES:
        session["view_as"] = role
        flash(f"You now see the team projects as a {role.title()}.")
    else:
        session.pop("view_as", None)
        flash("You now see your own roles again.")
    return redirect(safe_next(request.form.get("next")))


@bp.route("/signup", methods=["GET", "POST"])
def signup():
    if g.user is not None:
        return redirect(url_for("main.home"))
    next_page = request.values.get("next", "")
    errors = {}
    username = display_name = ""
    if request.method == "POST":
        # A hidden field people never see. Only robots fill it in, and they get
        # the same page as everyone else, so they learn nothing from it.
        if request.form.get("website"):
            return redirect(url_for("auth.login"))
        username = clean_username(request.form.get("username", ""))[:USERNAME_MAX_LENGTH + 1]
        display_name = request.form.get("display_name", "").strip()
        password = request.form.get("password", "")
        problem = username_problem(username)
        if problem:
            errors["username"] = problem
        if len(display_name) > DISPLAY_NAME_MAX_LENGTH:
            errors["display_name"] = f"Use at most {DISPLAY_NAME_MAX_LENGTH} characters."
        problem = password_problem(password, request.form.get("confirm_password", ""))
        if problem:
            errors["password"] = problem
        if not errors:
            s = db.session()
            try:
                user = create_user(s, username, password, display_name=display_name or None)
                code = new_recovery_code(user)
                s.commit()
            except IntegrityError:
                s.rollback()
                errors["username"] = "That username is already taken."
            else:
                log_in(user)
                show_recovery_code(code)
                return redirect(url_for("auth.recovery_code", next=safe_next(next_page)))
    return render_template("signup.html", errors=errors, username=username, display_name=display_name,
                           next=next_page), 400 if errors else 200


@bp.get("/recovery-code")
@login_required
def recovery_code():
    """Shown once, straight after the code is made. A reload shows nothing."""
    code = session.pop("recovery_code", None)
    if code is None:
        return redirect(url_for("auth.settings"))
    return render_template("recovery_code.html", code=code, next=safe_next(request.args.get("next")))


@bp.route("/forgot", methods=["GET", "POST"])
def forgot():
    if g.user is not None:
        return redirect(url_for("auth.settings"))
    errors = {}
    username = ""
    if request.method == "POST":
        s = db.session()
        username = request.form.get("username", "")[:USERNAME_MAX_LENGTH]
        new = request.form.get("new_password", "")
        problem = password_problem(new, request.form.get("confirm_password", ""))
        if problem:
            errors["new_password"] = problem
        else:
            user, error = check_recovery(s, username, request.form.get("code", ""), utcnow())
            if error:
                errors["code"] = error
            else:
                set_password(user, new)
                code = new_recovery_code(user)  # each code works only once
                s.commit()
                log_in(user)
                show_recovery_code(code)
                flash("Your password has been changed.")
                return redirect(url_for("auth.recovery_code"))
    return render_template("forgot.html", errors=errors, username=username), 400 if errors else 200


@bp.post("/logout")
def logout():
    session.clear()
    flash("You have logged out.")
    return redirect(url_for("auth.login"))


@bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    errors = {}
    if request.method == "POST":
        not_demo("The demo can't change its account. Sign up to have your own.")
        action = request.form.get("action")
        s = db.session()
        if action == "name":
            name = request.form.get("display_name", "").strip()
            if not name or len(name) > DISPLAY_NAME_MAX_LENGTH:
                errors["display_name"] = f"Use 1 to {DISPLAY_NAME_MAX_LENGTH} characters."
            else:
                g.user.display_name = name
                s.commit()
                flash("Your name has been changed.")
                return redirect(url_for("auth.settings"))
        elif action in ("password", "recovery"):
            if not check_password_hash(g.user.password_hash, request.form.get("current_password", "")):
                errors[f"{action}_current"] = "That isn't your current password."
            if action == "password":
                new = request.form.get("new_password", "")
                problem = password_problem(new, request.form.get("confirm_password", ""))
                if problem:
                    errors["new_password"] = problem
            if not errors:
                if action == "password":
                    set_password(g.user, new)
                    s.commit()
                    # This device stays logged in; every other one is logged out.
                    session["session_version"] = g.user.session_version
                    flash("Your password has been changed.")
                    return redirect(url_for("auth.settings"))
                show_recovery_code(new_recovery_code(g.user))
                s.commit()
                return redirect(url_for("auth.recovery_code"))
    return render_template("settings.html", errors=errors), 400 if errors else 200


# ---------- Command line ----------

@click.command("set-password")
@with_appcontext
@click.argument("username")
def set_password_command(username):
    """Change a user's password (and unlock the account). Also ends their sessions."""
    s = db.session()
    user = find_user(s, username)
    if user is None:
        raise click.ClickException(f'There is no user "{username}".')
    password = click.prompt("Password", hide_input=True, confirmation_prompt=True)
    if len(password) < PASSWORD_MIN_LENGTH:
        raise click.ClickException(f"Use at least {PASSWORD_MIN_LENGTH} characters.")
    set_password(user, password)
    s.commit()
    click.echo("The password is changed.")


@click.command("purge-demos")
@with_appcontext
def purge_demos_command():
    """Delete the demos that have run out (starting a demo does this too)."""
    s = db.session()
    count = purge_demos(s, utcnow())
    s.commit()
    click.echo(f"Deleted {count} old demo users.")


def init_app(app):
    from . import permissions

    app.jinja_env.globals["csrf_token"] = csrf_token
    app.jinja_env.globals["can"] = permissions
    app.cli.add_command(set_password_command)
    app.cli.add_command(purge_demos_command)
