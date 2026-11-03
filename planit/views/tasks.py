"""The board, the task page, and everything done to a task.

A task's address uses its number in the project: /projects/3/tasks/12 is WEB-12.
Moves come from the board's drag and drop (fetch, answered with JSON) or from
the Move buttons (a plain form, answered with a redirect). Both go through
workflow.move(), so the rules are the same.
"""
from flask import Blueprint, abort, flash, g, jsonify, redirect, render_template, request, url_for

from .. import activity, db, permissions as can, projects, tasks as task_list, workflow
from ..auth import login_required, safe_next
from ..dates import utcnow
from ..models import STATUSES, User, WipLimit
from .projects import load, require

bp = Blueprint("tasks", __name__)


def load_task(project_id, number):
    project, access = load(project_id)
    task = task_list.get(db.session(), project, number)
    if task is None:
        abort(404)
    return project, access, task


def wants_json():
    return request.headers.get("Accept", "").startswith("application/json")


def go_back(project, task=None):
    default = (url_for("tasks.show", project_id=project.id, number=task.number) if task
               else url_for("tasks.board", project_id=project.id))
    return redirect(safe_next(request.form.get("next"), default))


@bp.get("/projects/<int:project_id>")
@login_required
def board(project_id):
    project, access = load(project_id)
    s = db.session()
    return render_template("project/board.html", project=project, access=access,
                           columns=task_list.board(s, project), limits=workflow.limits(s, project))


# ---------- Making a task ----------

def assignee_from_form(s, project, access):
    """The person chosen in the form, if this user may choose them. ("" = nobody.)"""
    chosen = request.form.get("assignee_id", "")
    if chosen == "":
        return None
    user = s.get(User, int(chosen)) if chosen.isdigit() else None
    if user is None or user not in projects.assignable(s, project):
        abort(400, "Choose someone who works on this project.")
    if not can.can_assign_anyone(access) and user.id != g.user.id:
        abort(403, "Only a Manager can give a task to someone else.")
    return user


@bp.route("/projects/<int:project_id>/tasks/new", methods=["GET", "POST"])
@login_required
def new(project_id):
    project, access = load(project_id)
    require(can.can_create_task(access))
    s = db.session()
    values, errors = {"status": request.values.get("status", "todo")}, {}
    if request.method == "POST":
        values, errors = task_list.clean_form(request.form)
        status = request.form.get("status", "todo")
        assignee = assignee_from_form(s, project, access)
        if not errors:
            task = task_list.create(s, project, g.user, values.pop("title"), status, **values)
            if assignee:
                task_list.assign(s, task, assignee, g.user)
            s.commit()
            if request.form.get("quick"):
                return redirect(url_for("tasks.board", project_id=project.id) + f"#column-{task.status}")
            flash(f"{task.key} was added.")
            return redirect(url_for("tasks.show", project_id=project.id, number=task.number))
        if request.form.get("quick"):
            flash("A task needs a title of 1 to 200 characters.")
            return redirect(url_for("tasks.board", project_id=project.id))
        values["status"] = status
        values["assignee_id"] = request.form.get("assignee_id", "")
    return render_template("project/task_form.html", project=project, access=access, task=None, values=values,
                           errors=errors, people=projects.assignable(s, project)), 400 if errors else 200


# ---------- The task page and editing ----------

@bp.get("/projects/<int:project_id>/tasks/<int:number>")
@login_required
def show(project_id, number):
    project, access, task = load_task(project_id, number)
    s = db.session()
    return render_template("project/task.html", project=project, access=access, task=task,
                           moves=workflow.allowed_moves(access, task), history=activity.for_task(s, task),
                           people=projects.assignable(s, project))


@bp.route("/projects/<int:project_id>/tasks/<int:number>/edit", methods=["GET", "POST"])
@login_required
def edit(project_id, number):
    project, access, task = load_task(project_id, number)
    require(can.can_edit_task(access, task))
    s = db.session()
    values = {"title": task.title, "description": task.description, "due_date": task.due_date,
              "assignee_id": task.assignee_id or ""}
    errors = {}
    if request.method == "POST":
        new_values, errors = task_list.clean_form(request.form)
        values.update(new_values)
        if not errors:
            changed = any(getattr(task, name) != value for name, value in new_values.items())
            for name, value in new_values.items():
                setattr(task, name, value)
            if can.can_assign_anyone(access) and "assignee_id" in request.form:
                task_list.assign(s, task, assignee_from_form(s, project, access), g.user)
            if changed:
                task.updated_at = utcnow()
                activity.log(s, project, g.user, activity.EDITED, task)
            s.commit()
            flash("The task was saved.")
            return redirect(url_for("tasks.show", project_id=project.id, number=task.number))
    return render_template("project/task_form.html", project=project, access=access, task=task, values=values,
                           errors=errors, people=projects.assignable(s, project)), 400 if errors else 200


@bp.post("/projects/<int:project_id>/tasks/<int:number>/delete")
@login_required
def delete(project_id, number):
    project, access, task = load_task(project_id, number)
    require(can.can_delete_task(access, task), "Only a Manager or the owner can delete a task.")
    s = db.session()
    activity.log(s, project, g.user, activity.DELETED, task)
    key = task.key
    s.delete(task)
    s.commit()
    flash(f"{key} was deleted.")
    return redirect(url_for("tasks.board", project_id=project.id))


# ---------- Moving and assigning ----------

@bp.post("/projects/<int:project_id>/tasks/<int:number>/move")
@login_required
def move(project_id, number):
    project, access, task = load_task(project_id, number)
    s = db.session()
    to = request.form.get("to", "")
    problem = workflow.move(s, access, task, to)
    if problem:
        s.rollback()
        if wants_json():
            return jsonify(ok=False, message=problem), 409
        flash(problem)
        return go_back(project, task)
    s.commit()
    message = f"{task.key} moved to {workflow.name(to)}."
    if wants_json():
        return jsonify(ok=True, message=message)
    flash(message)
    return go_back(project, task)


@bp.post("/projects/<int:project_id>/tasks/<int:number>/assign")
@login_required
def assign(project_id, number):
    """Managers choose anyone; Members can only "Take it" or "Hand back"."""
    project, access, task = load_task(project_id, number)
    s = db.session()
    action = request.form.get("action")
    if action == "take":
        require(can.can_take_task(access, task), "Only an unassigned task can be taken.")
        task_list.assign(s, task, g.user, g.user)
        flash(f"{task.key} is yours now.")
    elif action == "drop":
        require(can.can_drop_task(access, task))
        task_list.assign(s, task, None, g.user)
        flash(f"You handed back {task.key}.")
    else:
        require(can.can_assign_anyone(access), "Only a Manager can give a task to someone else.")
        user = assignee_from_form(s, project, access)
        task_list.assign(s, task, user, g.user)
        flash(f"{task.key} is now {'with ' + user.display_name if user else 'unassigned'}.")
    s.commit()
    return go_back(project, task)


# ---------- History and limits ----------

@bp.get("/projects/<int:project_id>/activity")
@login_required
def history(project_id):
    project, access = load(project_id)
    return render_template("project/activity.html", project=project, access=access,
                           entries=activity.for_project(db.session(), project))


@bp.post("/projects/<int:project_id>/limits")
@login_required
def set_limits(project_id):
    project, access = load(project_id)
    require(can.can_set_limits(access))
    s = db.session()
    for status in STATUSES:
        field = request.form.get(f"limit_{status}")
        if field is None:
            continue
        limit = s.get(WipLimit, (project.id, status))
        number = int(field) if field.strip().isdigit() and int(field) > 0 else None
        if number is None and limit is not None:
            s.delete(limit)
        elif number is not None and limit is None:
            s.add(WipLimit(project_id=project.id, status=status, max_tasks=min(number, 99)))
        elif number is not None:
            limit.max_tasks = min(number, 99)
    s.commit()
    flash("The column limits were saved.")
    return redirect(url_for("projects.settings", project_id=project.id) + "#limits")
