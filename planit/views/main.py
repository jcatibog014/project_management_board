"""The pages that gather work from every project: Home and the Inbox. Also what
every page needs: the sidebar's project list, the unread count and the project tabs."""
from flask import Blueprint, abort, g, redirect, render_template, url_for

from .. import db, notify, projects, workflow
from ..auth import login_required
from ..dates import today, utcnow
from ..models import Notification

bp = Blueprint("main", __name__)


def project_tabs(project):
    """(name, endpoint, label) of the tabs at the top of a project."""
    tabs = [("board", "tasks.board", "Board"), ("activity", "tasks.history", "Activity")]
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


@bp.get("/")
@login_required
def home():
    return render_template("home.html")


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
