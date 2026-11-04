"""The pages that gather work from every project: Home, My Tasks, Calendar, Search and the Inbox.
Also what every page needs: the sidebar's project list, the unread count and the project tabs."""
from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from .. import activity, db, notify, permissions as can, planning, projects, search as finder, tasks as task_list, workflow
from ..auth import login_required
from ..dates import to_local, today, utcnow
from ..models import DONE, IN_PROGRESS, REVIEW, Notification

bp = Blueprint("main", __name__)


def project_tabs(project):
    """(name, endpoint, label) of the tabs at the top of a project."""
    tabs = [("board", "tasks.board", "Board"), ("list", "tasks.task_list_view", "List"),
            ("calendar", "tasks.project_calendar", "Calendar"), ("dashboard", "tasks.dashboard", "Dashboard"),
            ("activity", "tasks.history", "Activity")]
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
    return render_template("calendar.html", project=None,
                           **planning.calendar_page(db.session(), g.user, request.args))


@bp.get("/search")
@login_required
def search():
    s = db.session()
    text = finder.clean(request.args.get("q"))
    found_projects, found_tasks = finder.find(s, g.user, text)
    return render_template("search.html", text=text, found_projects=found_projects, found_tasks=found_tasks,
                           recent=projects.visible(s, g.user))


# ---------- Inbox ----------

@bp.get("/inbox")
@login_required
def inbox():
    s = db.session()
    show = request.args.get("show") if request.args.get("show") in notify.FILTERS else None
    notes = notify.inbox(s, g.user, show)
    # Approve and Send back, right in the Inbox: only on a review that is still waiting,
    # and only the buttons this person may press (the same rules as the board).
    actions = {}
    for note in notes:
        if note.kind == "review" and note.task is not None and note.task.status == REVIEW:
            moves = dict(workflow.allowed_moves(can.access_for(s, g.user, note.project), note.task))
            actions[note.id] = [(to, moves[to]) for to in (IN_PROGRESS, DONE) if to in moves]
    return render_template("inbox.html", notes=notes, show=show, actions=actions,
                           unread_total=notify.unread_count(s, g.user))


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


@bp.post("/inbox/<int:note_id>/review")
@login_required
def review_from_inbox(note_id):
    """Approve or send back the task a review note is about, then mark the note read."""
    s = db.session()
    note = s.get(Notification, note_id)
    if note is None or note.user_id != g.user.id or note.task is None:
        abort(404)
    to = request.form.get("to")
    if to not in (DONE, IN_PROGRESS):
        abort(400)
    task = note.task
    problem = workflow.move(s, can.access_for(s, g.user, note.project), task, to)
    if problem:
        s.rollback()
        flash(problem)
    else:
        note.read_at = note.read_at or utcnow()
        s.commit()
        flash(f"{task.key} {'is Done' if to == DONE else 'went back to In Progress'}.")
    return redirect(url_for("main.inbox", show=request.form.get("show") or None))


@bp.post("/inbox/read")
@login_required
def read_all():
    s = db.session()
    notify.mark_all_read(s, g.user)
    s.commit()
    return redirect(url_for("main.inbox"))
