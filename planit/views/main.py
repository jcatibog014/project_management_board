"""The pages that gather work from every project: Home. Also what every page
needs: the sidebar's project list and the project tabs."""
from flask import Blueprint, g, render_template

from .. import db, projects
from ..auth import login_required

bp = Blueprint("main", __name__)


def project_tabs(project):
    """(name, endpoint, label) of the tabs at the top of a project."""
    tabs = [("board", "tasks.board", "Board")]
    if project.is_team:
        tabs.append(("members", "projects.members", "Members"))
    tabs.append(("settings", "projects.settings", "Settings"))
    return tabs


@bp.app_context_processor
def everywhere():
    def sidebar_projects():
        return projects.visible(db.session(), g.user) if g.user else []
    return {"sidebar_projects": sidebar_projects, "project_tabs": project_tabs}


@bp.get("/")
@login_required
def home():
    return render_template("home.html")
