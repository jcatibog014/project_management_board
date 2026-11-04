"""The pages that gather work from every project: Home, My Tasks, Calendar and the Inbox. Also what
every page needs: the sidebar's project list, the unread count and the project tabs."""
from calendar import month_name

from flask import Blueprint, abort, g, redirect, render_template, request, url_for

from .. import activity, db, notify, planning, projects, tasks as task_list, workflow
from ..auth import login_required
from ..dates import to_local, today, utcnow
from ..models import Notification

bp = Blueprint("main", __name__)


def project_tabs(project):
    """(name, endpoint, label) of the tabs at the top of a project."""
    tabs = [("board", "tasks.board", "Board"), ("list", "tasks.task_list_view", "List"),
            ("calendar", "tasks.project_calendar", "Calendar"), ("activity", "tasks.history", "Activity")]
    if project.is_team:
        tabs.append(("members", "projects.members", "Members"))
    tabs.append(("settings", "projects.settings", "Settings"))
    return tabs


@bp.app_context_processor
def everywhere():
    def sidebar_projects():
        return projects.visible(db.session(), g.user) if g.user else []
    def unread():
        return notify.unread_count(db.session(), g.user) if g.user else 0
    return {"sidebar_projects": sidebar_projects, "project_tabs": project_tabs, "workflow": workflow,
            "today": today, "unread": unread}


def greeting():
    hour = to_local(utcnow()).hour
    return "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"


@bp.get("/")
@login_required
def home():
    s = db.session()
    day = today()
    mine = planning.my_open_tasks(s, g.user)
    counts = {name: len(rows) for name, rows in planning.grouped(mine, day)}
    active = projects.visible(s, g.user)
    return render_template(
        "home.html", greeting=greeting(), mine=mine[:6], counts=counts, open_count=len(mine),
        review=planning.waiting_for_review(s, g.user), active=active, stats=task_list.project_stats(s, active),
        feed=activity.for_projects(s, projects.visible_filter(g.user), limit=10))


@bp.get("/my-tasks")
@login_required
def my_tasks():
    s = db.session()
    return render_template("my_tasks.html", groups=planning.grouped(planning.my_open_tasks(s, g.user)),
                           review=planning.waiting_for_review(s, g.user))


@bp.get("/calendar")
@login_required
def calendar():
    year, month = planning.month_of(request.args.get("month"))
    previous, following = planning.next_and_previous(year, month)
    return render_template("calendar.html", weeks=planning.calendar(db.session(), g.user, year, month),
                           month_name=f"{month_name[month]} {year}", previous=previous, following=following,
                           project=None)


# ---------- Inbox ----------

@bp.get("/inbox")
@login_required
def inbox():
    return render_template("inbox.html", notes=notify.inbox(db.session(), g.user))


@bp.get("/inbox/<int:note_id>")
@login_required
def open_note(note_id):
    """Mark it read and go to what it is about."""
    s = db.session()
    note = s.get(Notification, note_id)
    if note is None or note.user_id != g.user.id:
        abort(404)
    if note.read_at is None:
        note.read_at = utcnow()
        s.commit()
    if note.task is not None:
        anchor = f"#comment-{note.comment_id}" if note.comment_id else ""
        return redirect(url_for("tasks.show", project_id=note.project_id, number=note.task.number) + anchor)
    return redirect(url_for("tasks.board", project_id=note.project_id))


@bp.post("/inbox/read")
@login_required
def read_all():
    s = db.session()
    notify.mark_all_read(s, g.user)
    s.commit()
    return redirect(url_for("main.inbox"))
