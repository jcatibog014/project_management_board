"""The workflow: the columns a task moves through, and the rules for moving.

    Backlog <-> To Do <-> In Progress <-> In Review --> Done
                  ^                                      |
                  +------------ reopen ------------------+

Rules (on top of the allowed moves above):
  - Viewers move nothing, and an archived project is read-only.
  - A Member moves only the tasks given to them.
  - Only a Manager or the owner approves (In Review -> Done) or reopens (Done -> To Do).
  - A task needs someone assigned before it can go to In Progress.
  - A column with a Work in Progress limit takes no more tasks once full.

move_problem() is the pure part (no database), tested as a table in
tests/test_workflow.py. move() checks it, checks the limit, moves the task,
and writes the history.
"""
from sqlalchemy import func, select

from . import activity, notify
from .dates import utcnow
from .models import APPROVED, BACKLOG, DONE, IN_PROGRESS, MANAGER, MEMBER, REOPENED, REVIEW, REVIEW_ASKED, SENT_BACK, \
    STATUSES, TODO, Task, WipLimit

NAMES = {BACKLOG: "Backlog", TODO: "To Do", IN_PROGRESS: "In Progress", REVIEW: "In Review", DONE: "Done"}

TRANSITIONS = {
    BACKLOG: (TODO,),
    TODO: (BACKLOG, IN_PROGRESS),
    IN_PROGRESS: (TODO, REVIEW),
    REVIEW: (IN_PROGRESS, DONE),
    DONE: (TODO,),
}

# What each move is called on its button.
ACTIONS = {
    (BACKLOG, TODO): "Move to To Do",
    (TODO, BACKLOG): "Back to Backlog",
    (TODO, IN_PROGRESS): "Start work",
    (IN_PROGRESS, TODO): "Stop work",
    (IN_PROGRESS, REVIEW): "Ask for review",
    (REVIEW, IN_PROGRESS): "Send back",
    (REVIEW, DONE): "Approve",
    (DONE, TODO): "Reopen",
}


def name(status):
    return NAMES[status]


def move_problem(access, task, to):
    """Why this person can't move this task to `to`, or None if they can."""
    if to not in STATUSES:
        return "That column doesn't exist."
    if to == task.status:
        return f"The task is already in {name(to)}."
    if not access.writable:
        return "This project is archived, so it is read-only." if access.archived else "You can't move tasks here."
    if not access.at_least(MEMBER):
        return "Viewers can look and comment, but not move tasks."
    if to not in TRANSITIONS[task.status]:
        return f"A task can't go from {name(task.status)} straight to {name(to)}."
    if task.status == REVIEW and to == DONE and not access.at_least(MANAGER):
        return "Only a Manager or the owner can approve a task."
    if task.status == DONE and not access.at_least(MANAGER):
        return "Only a Manager or the owner can reopen a task."
    if access.role == MEMBER and task.assignee_id != access.user.id:
        return "Members can only move the tasks given to them."
    if to == IN_PROGRESS and task.assignee_id is None:
        return "Give the task to someone before starting it."
    return None


def allowed_moves(access, task):
    """[(status, button text)] this person may press for this task (limits not checked)."""
    return [(to, ACTIONS[(task.status, to)]) for to in TRANSITIONS[task.status]
            if move_problem(access, task, to) is None]


def limits(s, project):
    """{status: max tasks} for the columns that have a limit."""
    return dict(s.execute(select(WipLimit.status, WipLimit.max_tasks).where(WipLimit.project_id == project.id)).all())


def counts(s, project):
    """{status: how many tasks}, with every status present."""
    found = dict(s.execute(select(Task.status, func.count()).where(Task.project_id == project.id)
                           .group_by(Task.status)).all())
    return {status: found.get(status, 0) for status in STATUSES}


def limit_problem(s, project, to):
    limit = limits(s, project).get(to)
    if limit is not None and counts(s, project)[to] >= limit:
        return f"{name(to)} is full ({limit} of {limit}). Finish or move a task there first."
    return None


def move(s, access, task, to):
    """Move the task, or return the reason it can't move. The caller commits."""
    problem = move_problem(access, task, to) or limit_problem(s, task.project, to)
    if problem:
        return problem
    before = task.status
    task.status = to
    now = utcnow()
    task.updated_at = now
    if to == DONE:
        task.completed_at = now
    elif before == DONE:
        task.completed_at = None
    verb = activity.verb_for_move(before, to)
    activity.log(s, task.project, access.user, verb, task, from_status=before, to_status=to)
    if to == REVIEW:
        notify.send(s, notify.managers(s, task.project), REVIEW_ASKED, access.user, task.project, task)
    elif verb in (activity.APPROVED, activity.SENT_BACK, activity.REOPENED):
        kind = {activity.APPROVED: APPROVED, activity.SENT_BACK: SENT_BACK, activity.REOPENED: REOPENED}[verb]
        notify.send(s, [task.assignee], kind, access.user, task.project, task)
    return None
