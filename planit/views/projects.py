"""Projects: the list, making one, its people (Members) and its settings.

Every route starts with load(): a project you can't see is a 404, so its
name never leaks. Something you can see but may not do is a 403.
"""
from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for
from sqlalchemy import select

from .. import db, invites, permissions as can, projects, tasks, workflow
from ..auth import login_required, not_demo
from ..dates import utcnow
from ..models import COLORS, MEMBER, PERSONAL, TEAM, Label, Project, ProjectMember, ProjectTeam, Team, \
    User, team_members

bp = Blueprint("projects", __name__)


def load(project_id):
    """(project, access) for this user, or 404 if they can't see it."""
    s = db.session()
    project = s.get(Project, project_id)
    if project is None:
        abort(404)
    access = can.access_for(s, g.user, project)
    if not can.can_view_project(access):
        abort(404)
    return project, access


def require(allowed, message=None):
    if not allowed:
        abort(403, message)


def my_teams(s):
    """The Teams this user is in or made, for the Add Team choice."""
    return s.scalars(select(Team).where(
        (Team.created_by_id == g.user.id)
        | Team.id.in_(select(team_members.c.team_id).where(team_members.c.user_id == g.user.id)))
        .order_by(Team.name)).all()


def form_choice(name, allowed):
    value = request.form.get(name, "")
    if value not in allowed:
        abort(400, "Please choose one of the options.")
    return value


# ---------- The list and New Project ----------

@bp.get("/projects")
@login_required
def index():
    s = db.session()
    active, archived = projects.visible(s, g.user), projects.visible(s, g.user, archived=True)
    return render_template("projects.html", active=active, archived=archived,
                           stats=tasks.project_stats(s, active + archived))


@bp.route("/projects/new", methods=["GET", "POST"])
@login_required
def new():
    s = db.session()
    teams = my_teams(s)
    values, errors = {"color": "blue"}, {}
    kind = request.form.get("kind", request.args.get("kind", PERSONAL))
    if request.method == "POST":
        values, errors = projects.clean_form(request.form)
        if kind not in (PERSONAL, TEAM):
            kind = PERSONAL
        chosen_teams = [team for team in teams if str(team.id) in request.form.getlist("team_ids")]
        people, missing = [], []
        for name in request.form.get("usernames", "").replace(",", " ").split():
            user = projects.find_user(s, name)
            (people.append(user) if user else missing.append(name))
        if missing:
            errors["usernames"] = "We couldn't find: " + ", ".join(missing)
        if not errors:
            project = projects.create(s, g.user, values, kind)
            tasks.add_starter_labels(s, project)
            if kind == TEAM:
                for team in chosen_teams:
                    projects.add_team(s, project, team, MEMBER)
                for user in people:
                    projects.add_person(s, project, user, MEMBER)
            s.commit()
            flash(f"{project.name} is ready. Add your first task.")
            return redirect(url_for("tasks.board", project_id=project.id))
        values["usernames"] = request.form.get("usernames", "")
        values["team_ids"] = request.form.getlist("team_ids")
    return render_template("project/new.html", values=values, errors=errors, kind=kind, teams=teams,
                           colors=COLORS), 400 if errors else 200


# ---------- Members ----------

@bp.get("/projects/<int:project_id>/members")
@login_required
def members(project_id):
    project, access = load(project_id)
    if not project.is_team:
        return redirect(url_for("projects.settings", project_id=project.id))
    s = db.session()
    new_link = session.pop("new_invite", None)
    if new_link and new_link.get("project_id") != project.id:
        new_link = None
    linked_team_ids = {link.team_id for link in project.teams}
    return render_template(
        "project/members.html", project=project, access=access, people=projects.people(s, project),
        team_links=sorted(project.teams, key=lambda link: link.team.name.lower()),
        addable_teams=[team for team in my_teams(s) if team.id not in linked_team_ids],
        invites=invites.waiting(s, project, utcnow()) if can.can_manage_people(access) else [],
        role_choices=projects.role_choices(can.roles_you_can_give(access)), new_link=new_link)


def back_to_members(project, message=None):
    if message:
        flash(message)
    return redirect(url_for("projects.members", project_id=project.id))


@bp.post("/projects/<int:project_id>/members/add")
@login_required
def add_person(project_id):
    project, access = load(project_id)
    require(can.can_manage_people(access))
    s = db.session()
    role = form_choice("role", can.roles_you_can_give(access))
    user = projects.find_user(s, request.form.get("username", ""))
    if user is None:
        return back_to_members(project, "We couldn't find anyone with that username.")
    current = s.get(ProjectMember, (project.id, user.id))
    if current is not None:
        require(can.can_change_role(access, current.role), "Only the owner can change a Manager.")
    message = projects.add_person(s, project, user, role)
    s.commit()
    return back_to_members(project, message)


@bp.post("/projects/<int:project_id>/members/<int:user_id>")
@login_required
def change_person(project_id, user_id):
    """Change someone's own role, or remove it ("remove" button)."""
    project, access = load(project_id)
    s = db.session()
    link = s.get(ProjectMember, (project.id, user_id))
    if link is None:
        abort(404)
    require(can.can_change_role(access, link.role), "Only the owner can change a Manager.")
    name = link.user.display_name
    if request.form.get("action") == "remove":
        s.delete(link)
        message = f"{name} was removed. A Team can still give them access."
    else:
        link.role = form_choice("role", can.roles_you_can_give(access))
        message = f"{name} is now {link.role.title()}."
    s.commit()
    return back_to_members(project, message)


@bp.post("/projects/<int:project_id>/teams/add")
@login_required
def add_team(project_id):
    project, access = load(project_id)
    require(can.can_manage_people(access))
    s = db.session()
    role = form_choice("role", can.roles_you_can_give(access))
    team = s.get(Team, request.form.get("team_id", type=int) or 0)
    # Only Teams you are in: you can't pull strangers' Teams into your project.
    if team is None or team not in my_teams(s):
        abort(404)
    current = s.get(ProjectTeam, (project.id, team.id))
    if current is not None:
        require(can.can_change_role(access, current.role), "Only the owner can change a Manager.")
    message = projects.add_team(s, project, team, role)
    s.commit()
    return back_to_members(project, message)


@bp.post("/projects/<int:project_id>/teams/<int:team_id>")
@login_required
def change_team(project_id, team_id):
    project, access = load(project_id)
    s = db.session()
    link = s.get(ProjectTeam, (project.id, team_id))
    if link is None:
        abort(404)
    require(can.can_change_role(access, link.role), "Only the owner can change a Manager.")
    name = link.team.name
    if request.form.get("action") == "remove":
        s.delete(link)
        message = f"{name} was removed. Its people lost the access it gave them."
    else:
        link.role = form_choice("role", can.roles_you_can_give(access))
        message = f"{name} is now {link.role.title()}."
    s.commit()
    return back_to_members(project, message)


@bp.post("/projects/<int:project_id>/leave")
@login_required
def leave(project_id):
    project, access = load(project_id)
    require(can.can_leave_project(access))
    s = db.session()
    link = s.get(ProjectMember, (project.id, g.user.id))
    if link is not None:
        s.delete(link)
        s.commit()
    g.pop("roles", None)
    if can.stored_role(s, g.user, project):
        flash(f"You left {project.name}, but a Team you are in still shares it. Leave the Team to lose access.")
        return redirect(url_for("tasks.board", project_id=project.id))
    flash(f"You left {project.name}.")
    return redirect(url_for("projects.index"))


# ---------- Invite links ----------

@bp.post("/projects/<int:project_id>/invites")
@login_required
def new_invite(project_id):
    project, access = load(project_id)
    require(can.can_manage_people(access))
    not_demo("The demo can't make real invite links. Add a sample person by username instead.")
    s = db.session()
    role = form_choice("role", can.roles_you_can_give(access))
    token = invites.create(s, project, role, g.user, utcnow())
    s.commit()
    # Shown once on the next page: only its hash is kept.
    session["new_invite"] = {"project_id": project.id, "role": role,
                             "url": url_for("projects.join", token=token, _external=True)}
    return redirect(url_for("projects.members", project_id=project.id) + "#invites")


@bp.post("/projects/<int:project_id>/invites/<int:invite_id>/cancel")
@login_required
def cancel_invite(project_id, invite_id):
    project, access = load(project_id)
    require(can.can_manage_people(access))
    s = db.session()
    invite = next((i for i in invites.waiting(s, project, utcnow()) if i.id == invite_id), None)
    if invite is None:
        abort(404)
    s.delete(invite)
    s.commit()
    return back_to_members(project, "The link was cancelled.")


@bp.route("/join/<token>", methods=["GET", "POST"])
@login_required
def join(token):
    s = db.session()
    now = utcnow()
    invite = invites.find_usable(s, token, now)
    if invite is None:
        return render_template("join.html", invite=None), 404
    project = invite.project
    current = can.stored_role(s, g.user, project)
    if request.method == "POST":
        not_demo("The demo can't join real projects.")
        if current and can.at_least(current, invite.role):
            flash(f"You are already in {project.name}.")
        elif not invites.claim(s, invite, g.user, now):
            s.rollback()
            return render_template("join.html", invite=None), 409
        else:
            projects.add_person(s, project, g.user, invite.role)
            s.commit()
            flash(f"Welcome to {project.name}! You joined as {invite.role.title()}.")
        return redirect(url_for("tasks.board", project_id=project.id))
    return render_template("join.html", invite=invite, current=current)


# ---------- Project Settings ----------

@bp.route("/projects/<int:project_id>/settings", methods=["GET", "POST"])
@login_required
def settings(project_id):
    project, access = load(project_id)
    s = db.session()
    errors = {}
    values = {"name": project.name, "key": project.key, "description": project.description,
              "color": project.color, "due_date": project.due_date}
    if request.method == "POST":
        require(can.can_edit_project(access))
        values, errors = projects.clean_form(request.form)
        if not errors:
            for name, value in values.items():
                setattr(project, name, value)
            s.commit()
            flash("The project was saved.")
            return redirect(url_for("projects.settings", project_id=project.id))
    candidates = [person.user for person in projects.people(s, project)
                  if not person.is_owner and person.direct_role]
    return render_template("project/settings.html", project=project, access=access, values=values,
                           errors=errors, colors=COLORS, candidates=candidates,
                           limits=workflow.limits(s, project), labels=tasks.project_labels(s, project)), \
        400 if errors else 200


@bp.post("/projects/<int:project_id>/labels")
@login_required
def add_label(project_id):
    project, access = load(project_id)
    require(can.can_manage_labels(access))
    s = db.session()
    name, color, problem = tasks.clean_label(request.form)
    if not problem and any(label.name.lower() == name.lower() for label in tasks.project_labels(s, project)):
        problem = f"There is already a label called {name}."
    if problem:
        flash(problem)
    else:
        s.add(Label(project_id=project.id, name=name, color=color))
        s.commit()
        flash(f"The label {name} was added.")
    return redirect(url_for("projects.settings", project_id=project.id) + "#labels")


@bp.post("/projects/<int:project_id>/labels/<int:label_id>")
@login_required
def change_label(project_id, label_id):
    project, access = load(project_id)
    require(can.can_manage_labels(access))
    s = db.session()
    label = s.get(Label, label_id)
    if label is None or label.project_id != project.id:
        abort(404)
    if request.form.get("action") == "delete":
        s.delete(label)
        s.commit()
        flash(f"The label {label.name} was deleted. Its tasks keep everything else.")
    else:
        name, color, problem = tasks.clean_label(request.form)
        clash = any(other.id != label.id and other.name.lower() == name.lower()
                    for other in tasks.project_labels(s, project))
        if problem or clash:
            flash(problem or f"There is already a label called {name}.")
        else:
            label.name, label.color = name, color
            s.commit()
            flash("The label was saved.")
    return redirect(url_for("projects.settings", project_id=project.id) + "#labels")


@bp.post("/projects/<int:project_id>/archive")
@login_required
def archive(project_id):
    project, access = load(project_id)
    require(can.can_archive_project(access))
    project.archived_at = None if project.is_archived else utcnow()
    db.session().commit()
    flash(f"{project.name} was archived. It is read-only now." if project.is_archived
          else f"{project.name} is back.")
    return redirect(url_for("projects.settings", project_id=project.id))


@bp.post("/projects/<int:project_id>/kind")
@login_required
def change_kind(project_id):
    project, access = load(project_id)
    require(can.is_owner(access))
    if project.is_team:
        if projects.has_others(project):
            flash("Remove everyone else first: a Personal project is only yours.")
            return redirect(url_for("projects.settings", project_id=project.id))
        project.kind = PERSONAL
        message = f"{project.name} is a Personal project now."
    else:
        project.kind = TEAM
        message = f"{project.name} is a Team project now. Add people on the Members tab."
    db.session().commit()
    flash(message)
    target = "projects.members" if project.is_team else "projects.settings"
    return redirect(url_for(target, project_id=project.id))


@bp.post("/projects/<int:project_id>/transfer")
@login_required
def transfer(project_id):
    project, access = load(project_id)
    require(can.is_owner(access))
    s = db.session()
    new_owner = s.get(User, request.form.get("user_id", type=int) or 0)
    # Only someone who was added themselves (not just through a Team), so they can't lose it by leaving a Team.
    if new_owner is None or s.get(ProjectMember, (project.id, new_owner.id)) is None:
        abort(400, "Choose someone who was added to this project.")
    projects.transfer(s, project, new_owner)
    s.commit()
    flash(f"{new_owner.display_name} owns {project.name} now. You are a Manager.")
    return redirect(url_for("tasks.board", project_id=project.id))


@bp.post("/projects/<int:project_id>/delete")
@login_required
def delete(project_id):
    project, access = load(project_id)
    require(can.is_owner(access))
    if request.form.get("confirm_name", "").strip() != project.name:
        flash("Type the project's name exactly to delete it.")
        return redirect(url_for("projects.settings", project_id=project.id))
    s = db.session()
    name = project.name
    s.delete(project)
    s.commit()
    flash(f"{name} was deleted.")
    return redirect(url_for("projects.index"))
