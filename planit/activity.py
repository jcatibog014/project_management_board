"""A project's history: one Activity row for everything that happens to a task.

The templates turn a row into a sentence (_activity.html), so the words can
change without touching the stored history.
"""
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from .dates import utcnow
from .models import DONE, IN_PROGRESS, REVIEW, Activity, Project

# The verbs, and the moves that have their own.
CREATED, MOVED, APPROVED, SENT_BACK, REOPENED = "created", "moved", "approved", "sent_back", "reopened"
ASSIGNED, UNASSIGNED, EDITED, DELETED, COMMENTED = "assigned", "unassigned", "edited", "deleted", "commented"


def verb_for_move(before, to):
    if before == REVIEW and to == DONE:
        return APPROVED
    if before == REVIEW and to == IN_PROGRESS:
        return SENT_BACK
    if before == DONE:
        return REOPENED
    return MOVED


def log(s, project, actor, verb, task=None, **fields):
    entry = Activity(project_id=project.id, task_id=task.id if task else None, actor_id=actor.id if actor else None,
                     verb=verb, note=f"{task.key} {task.title}"[:200] if task else "", created_at=utcnow(), **fields)
    s.add(entry)
    return entry


def _options():
    return (selectinload(Activity.actor), selectinload(Activity.other_user), selectinload(Activity.task))


def for_project(s, project, limit=100):
    return s.scalars(select(Activity).where(Activity.project_id == project.id).options(*_options())
                     .order_by(Activity.created_at.desc(), Activity.id.desc()).limit(limit)).all()


def for_task(s, task, limit=50):
    return s.scalars(select(Activity).where(Activity.task_id == task.id).options(*_options())
                     .order_by(Activity.created_at.desc(), Activity.id.desc()).limit(limit)).all()


def for_projects(s, project_filter, limit=12):
    """The newest lines across many projects (Home): project_filter is a WHERE on Project."""
    return s.scalars(select(Activity).join(Project, Project.id == Activity.project_id).where(project_filter)
                     .options(*_options(), selectinload(Activity.project))
                     .order_by(Activity.created_at.desc(), Activity.id.desc()).limit(limit)).all()


