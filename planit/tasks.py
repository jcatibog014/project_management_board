"""Tasks: making, changing and listing them. Moving them is in workflow.py.

Like projects.py, these functions change the session and never commit.
"""
from dataclasses import dataclass

from sqlalchemy import case, func, select, update
from sqlalchemy.orm import selectinload

from . import activity, notify, projects
from .dates import utcnow
from .models import ASSIGNED_TO_YOU, BACKLOG, COLORS, DONE, HIGH, LOW, MEDIUM, PRIORITIES, STATUSES, TODO, URGENT, \
    ChecklistItem, Comment, Label, Project, Task

TITLE_MAX_LENGTH = 200
DESCRIPTION_MAX_LENGTH = 10_000
# New tasks can only start at the beginning of the workflow.
START_STATUSES = (BACKLOG, TODO)
LABEL_MAX_LENGTH = 30
CHECK_MAX_LENGTH = 200
CHECKLIST_MAX_ITEMS = 50
# Every new project starts with these, so the label picker is never empty.
STARTER_LABELS = (("Bug", "red"), ("Feature", "blue"), ("Design", "purple"))


def card_options():
    """Load what a card shows in one go, not one query per card."""
    return (selectinload(Task.assignee), selectinload(Task.project), selectinload(Task.labels),
            selectinload(Task.checklist), selectinload(Task.comments).selectinload(Comment.author))


PRIORITY_RANK = case((Task.priority == URGENT, 0), (Task.priority == HIGH, 1), (Task.priority == MEDIUM, 2),
                     else_=3)


def order():
    """Most urgent first, then the soonest deadline (no deadline last), then oldest first."""
    return (PRIORITY_RANK, case((Task.due_date.is_(None), 1), else_=0), Task.due_date, Task.number)


def board_rows(s, project):
    """Every task in the project, with what a card shows, most urgent first."""
    return s.scalars(select(Task).where(Task.project_id == project.id).options(*card_options())
                     .order_by(*order())).all()


def board(s, project):
    """{status: [tasks]} for every column."""
    columns = {status: [] for status in STATUSES}
    for task in board_rows(s, project):
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
    if "priority" in form:
        values["priority"] = form.get("priority") if form.get("priority") in PRIORITIES else MEDIUM
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
        notify.send(s, [user], ASSIGNED_TO_YOU, actor, task.project, task)
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




# ---------- Labels ----------

def project_labels(s, project):
    return s.scalars(select(Label).where(Label.project_id == project.id).order_by(Label.name)).all()


def add_starter_labels(s, project):
    for name, color in STARTER_LABELS:
        s.add(Label(project_id=project.id, name=name, color=color))


def clean_label(form):
    """(name, color, problem) from a label form."""
    name = " ".join(form.get("name", "").split())
    color = form.get("color") if form.get("color") in COLORS else "blue"
    if not name or len(name) > LABEL_MAX_LENGTH:
        return name, color, f"Use 1 to {LABEL_MAX_LENGTH} characters."
    return name, color, None


def chosen_labels(s, project, ids):
    """The project's labels whose ids were ticked (others are ignored)."""
    wanted = {int(i) for i in ids if str(i).isdigit()}
    return [label for label in project_labels(s, project) if label.id in wanted]


# ---------- Checklist ----------

def add_check(task, text):
    """Add a step at the end. Returns a problem or None."""
    text = " ".join((text or "").split())
    if not text or len(text) > CHECK_MAX_LENGTH:
        return f"A step needs 1 to {CHECK_MAX_LENGTH} characters."
    if len(task.checklist) >= CHECKLIST_MAX_ITEMS:
        return f"A task can have at most {CHECKLIST_MAX_ITEMS} steps."
    position = max((item.position for item in task.checklist), default=0) + 1
    task.checklist.append(ChecklistItem(text=text, position=position))
    task.updated_at = utcnow()
    return None


PRIORITY_NAMES = {LOW: "Low", MEDIUM: "Medium", HIGH: "High", URGENT: "Urgent"}
