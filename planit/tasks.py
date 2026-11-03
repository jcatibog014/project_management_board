"""Tasks: making, changing and listing them. Moving them is in workflow.py.

Like projects.py, these functions change the session and never commit.
"""
from dataclasses import dataclass

from sqlalchemy import case, func, select, update
from sqlalchemy.orm import selectinload

from . import activity, projects
from .dates import utcnow
from .models import BACKLOG, DONE, STATUSES, TODO, Project, Task

TITLE_MAX_LENGTH = 200
DESCRIPTION_MAX_LENGTH = 10_000
# New tasks can only start at the beginning of the workflow.
START_STATUSES = (BACKLOG, TODO)


def card_options():
    """Load what a card shows in one go, not one query per card."""
    return (selectinload(Task.assignee), selectinload(Task.project))


def order():
    """Soonest deadline first (no deadline last), then oldest first."""
    return (case((Task.due_date.is_(None), 1), else_=0), Task.due_date, Task.number)


def board(s, project):
    """{status: [tasks]} for every column."""
    columns = {status: [] for status in STATUSES}
    for task in s.scalars(select(Task).where(Task.project_id == project.id).options(*card_options())
                          .order_by(*order())):
        columns[task.status].append(task)
    # The newest finished work first: Done grows forever.
    columns[DONE].sort(key=lambda task: task.completed_at or task.updated_at, reverse=True)
    return columns


def get(s, project, number):
    return s.scalar(select(Task).where(Task.project_id == project.id, Task.number == number)
                    .options(*card_options()))


def clean_form(form):
    """(values, errors) from the task form. Only the fields that were sent."""
    values, errors = {}, {}
    if "title" in form:
        values["title"] = " ".join(form.get("title", "").split())
        if not values["title"] or len(values["title"]) > TITLE_MAX_LENGTH:
            errors["title"] = f"Use 1 to {TITLE_MAX_LENGTH} characters."
    if "description" in form:
        values["description"] = form.get("description", "").replace("\r\n", "\n").strip()
        if len(values["description"]) > DESCRIPTION_MAX_LENGTH:
            errors["description"] = f"Use at most {DESCRIPTION_MAX_LENGTH:,} characters."
    if "due_date" in form:
        values["due_date"], problem = projects.parse_date(form.get("due_date", "").strip())
        if problem:
            errors["due_date"] = problem
    return values, errors


def create(s, project, reporter, title, status=TODO, **fields):
    """Add a task with the project's next number. The caller commits."""
    # "next_number = next_number + 1" runs in the database, which locks the
    # project's row until we commit. So two people adding a task at the same
    # moment get different numbers: the second waits for the first.
    s.execute(update(Project).where(Project.id == project.id).values(next_number=Project.next_number + 1))
    number = s.scalar(select(Project.next_number).where(Project.id == project.id)) - 1
    project.next_number = number + 1
    task = Task(project_id=project.id, project=project, number=number, title=title, reporter_id=reporter.id,
                status=status if status in START_STATUSES else TODO, created_at=utcnow(), updated_at=utcnow(),
                **fields)
    s.add(task)
    s.flush()
    activity.log(s, project, reporter, activity.CREATED, task, to_status=task.status)
    return task


def assign(s, task, user, actor):
    """Give the task to user (or to nobody, if None). The caller commits."""
    if (user.id if user else None) == task.assignee_id:
        return
    task.assignee_id = user.id if user else None
    task.assignee = user
    task.updated_at = utcnow()
    if user:
        activity.log(s, task.project, actor, activity.ASSIGNED, task, other_user_id=user.id)
    else:
        activity.log(s, task.project, actor, activity.UNASSIGNED, task)


@dataclass
class Stats:
    total: int = 0
    done: int = 0
    people: list = None

    @property
    def open(self):
        return self.total - self.done


def project_stats(s, project_list):
    """{project id: Stats} for project cards: how many tasks, how many done, and some faces."""
    ids = [project.id for project in project_list]
    stats = {project_id: Stats(people=[]) for project_id in ids}
    if not ids:
        return stats
    rows = s.execute(select(Task.project_id, func.count(), func.sum(case((Task.status == DONE, 1), else_=0)))
                     .where(Task.project_id.in_(ids)).group_by(Task.project_id)).all()
    for project_id, total, done in rows:
        stats[project_id].total, stats[project_id].done = total, done or 0
    for project in project_list:
        if project.is_team:
            stats[project.id].people = [person.user for person in projects.people(s, project)][:5]
    return stats


