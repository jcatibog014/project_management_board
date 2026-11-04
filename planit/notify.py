"""The Inbox: tell people about the things that need them.

    mentioned   someone wrote @you in a comment
    assigned    a task was given to you
    review      a task asks for review (to the project's Managers and owner)
    approved    your task was approved (to its assignee)
    sent_back   your task was sent back from review
    reopened    your finished task was reopened
    commented   a comment on a task you made or were given
    added       you were added to a project

Nobody is told about their own actions, and nobody is told about a project
they can't open.
"""
from sqlalchemy import func, select, update
from sqlalchemy.orm import selectinload

from . import permissions
from .dates import utcnow
from .models import MANAGER, Notification, Task


def send(s, users, kind, actor, project, task=None, comment=None):
    """One notification for each of these users (repeats and the actor left out)."""
    seen = set()
    for user in users:
        if user is None or user.id in seen or (actor is not None and user.id == actor.id):
            continue
        seen.add(user.id)
        if permissions.stored_role(s, user, project) is None:
            continue
        s.add(Notification(user_id=user.id, kind=kind, project_id=project.id, task_id=task.id if task else None,
                           comment_id=comment.id if comment else None, actor_id=actor.id if actor else None,
                           created_at=utcnow()))
    return seen


def managers(s, project):
    """The owner and everyone whose role is Manager (themselves or through a Team)."""
    from .projects import people

    return [person.user for person in people(s, project) if permissions.at_least(person.role, MANAGER)]


def unread_count(s, user):
    return s.scalar(select(func.count()).select_from(Notification)
                    .where(Notification.user_id == user.id, Notification.read_at.is_(None)))


def inbox(s, user, limit=60):
    return s.scalars(select(Notification).where(Notification.user_id == user.id)
                     .options(selectinload(Notification.actor), selectinload(Notification.project),
                              selectinload(Notification.comment),
                              selectinload(Notification.task).selectinload(Task.project))
                     .order_by(Notification.read_at.is_not(None), Notification.created_at.desc(),
                               Notification.id.desc())
                     .limit(limit)).all()


def mark_all_read(s, user):
    s.execute(update(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))
              .values(read_at=utcnow()))
