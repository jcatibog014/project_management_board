"""The board and its tasks."""
from flask import Blueprint, render_template

from ..auth import login_required
from .projects import load

bp = Blueprint("tasks", __name__)


@bp.get("/projects/<int:project_id>")
@login_required
def board(project_id):
    project, access = load(project_id)
    return render_template("project/board.html", project=project, access=access)
