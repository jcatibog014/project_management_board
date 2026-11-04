"""Teams: saved groups of people. Share a project with a Team and everyone in
it gets that role; take someone out of the Team and that access is gone.

Only the person who made a Team changes who is in it. Everyone in it can see
it and leave it.
"""
from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy import select

from .. import db, permissions as can, projects
from ..auth import login_required
from ..models import Project, ProjectTeam, Team, team_members

bp = Blueprint("teams", __name__)

NAME_MAX_LENGTH = 60


def load(team_id):
    team = db.session().get(Team, team_id)
    if team is None or not can.can_view_team(g.user, team):
        abort(404)
    return team


def require_manager(team):
    if not can.can_manage_team(g.user, team):
        abort(403, "Only the person who made this Team can change it.")


def clean_name(errors):
    name = request.form.get("name", "").strip()
    if not name or len(name) > NAME_MAX_LENGTH:
        errors["name"] = f"Use 1 to {NAME_MAX_LENGTH} characters."
    return name


@bp.route("/teams", methods=["GET", "POST"])
@login_required
def index():
    s = db.session()
    errors = {}
    if request.method == "POST":
        name = clean_name(errors)
        if not errors:
            team = Team(name=name, created_by_id=g.user.id)
            team.members.append(g.user)
            s.add(team)
            s.commit()
            flash(f"{team.name} is ready. Add the people in it.")
            return redirect(url_for("teams.show", team_id=team.id))
    teams = s.scalars(select(Team).where(
        (Team.created_by_id == g.user.id)
        | Team.id.in_(select(team_members.c.team_id).where(team_members.c.user_id == g.user.id)))
        .order_by(Team.name)).all()
    return render_template("teams.html", teams=teams, errors=errors), 400 if errors else 200


@bp.get("/teams/<int:team_id>")
@login_required
def show(team_id):
    team = load(team_id)
    s = db.session()
    shared = s.execute(select(Project, ProjectTeam.role).join(ProjectTeam, ProjectTeam.project_id == Project.id)
                       .where(ProjectTeam.team_id == team.id).order_by(Project.name)).all()
    # Only list the projects this person can open themselves; the rest are just counted.
    visible = [(project, role) for project, role in shared if can.effective_role(s, g.user, project)]
    return render_template("team.html", team=team, shared=visible, hidden_count=len(shared) - len(visible))


@bp.post("/teams/<int:team_id>/members")
@login_required
def add_member(team_id):
    team = load(team_id)
    require_manager(team)
    s = db.session()
    user = projects.find_user(s, request.form.get("username", ""), g.user)
    if user is None:
        flash("We couldn't find anyone with that username.")
    elif user in team.members:
        flash(f"{user.display_name} is already in {team.name}.")
    else:
        team.members.append(user)
        s.commit()
        flash(f"{user.display_name} joined {team.name}, and every project it shares.")
    return redirect(url_for("teams.show", team_id=team.id))


@bp.post("/teams/<int:team_id>/members/<int:user_id>/remove")
@login_required
def remove_member(team_id, user_id):
    team = load(team_id)
    leaving_myself = user_id == g.user.id
    if not leaving_myself:
        require_manager(team)
    elif team.created_by_id == g.user.id:
        abort(403, "You made this Team, so you can't leave it. Delete it instead.")
    s = db.session()
    user = next((member for member in team.members if member.id == user_id), None)
    if user is None:
        abort(404)
    team.members.remove(user)
    s.commit()
    if leaving_myself:
        flash(f"You left {team.name}.")
        return redirect(url_for("teams.index"))
    flash(f"{user.display_name} left {team.name}, and the projects it shares.")
    return redirect(url_for("teams.show", team_id=team.id))


@bp.post("/teams/<int:team_id>/rename")
@login_required
def rename(team_id):
    team = load(team_id)
    require_manager(team)
    errors = {}
    name = clean_name(errors)
    if errors:
        flash(errors["name"])
    else:
        team.name = name
        db.session().commit()
        flash("The Team was renamed.")
    return redirect(url_for("teams.show", team_id=team.id))


@bp.post("/teams/<int:team_id>/delete")
@login_required
def delete(team_id):
    team = load(team_id)
    require_manager(team)
    s = db.session()
    name = team.name
    s.delete(team)
    s.commit()
    flash(f"{name} was deleted. Projects it shared keep the people added on their own.")
    return redirect(url_for("teams.index"))
