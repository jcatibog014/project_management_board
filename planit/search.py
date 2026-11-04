"""Search: projects and tasks by name, or a task by its key (WEB-3).

Like every list, it starts from projects.visible_filter(), so a search never
finds anything in a project the person can't open.
"""
import re

from sqlalchemy import and_, or_, select

from . import projects, tasks as task_list
from .models import DONE, Project, Task

KEY = re.compile(r"([A-Za-z][A-Za-z0-9]{1,4})-(\d{1,6})")


def clean(text):
    return " ".join((text or "").split())[:100]


def find(s, user, text, limit=30):
    """([projects], [tasks]) that match the text. Finished tasks come last."""
    text = clean(text)
    if not text:
        return [], []
    visible = projects.visible_filter(user)
    found_projects = s.scalars(
        select(Project).where(visible, or_(Project.name.icontains(text, autoescape=True),
                                           Project.key == text.upper()))
        .order_by(Project.archived_at.is_not(None), Project.name).limit(10)).all()
    rule = Task.title.icontains(text, autoescape=True)
    key = KEY.fullmatch(text)
    if key:
        rule = or_(rule, and_(Project.key == key[1].upper(), Task.number == int(key[2])))
    found_tasks = s.scalars(
        select(Task).join(Project, Project.id == Task.project_id).where(visible, rule)
        .options(*task_list.card_options())
        .order_by(Task.status == DONE, *task_list.order()).limit(limit)).all()
    return found_projects, found_tasks
