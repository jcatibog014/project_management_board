"""Views of work across time: My Tasks, the calendar, a project's filtered list,
and what Home shows. Everything starts from projects.visible_filter(), so a
task in a project someone can't open never shows up.
"""
import calendar as month_calendar
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import and_, select

from . import projects, tasks as task_list
from .dates import today
from .models import DONE, MANAGER, PRIORITIES, REVIEW, STATUSES, Project, Task, task_labels

WEEK = 7
GROUPS = ("Overdue", "Today", "This Week", "Later", "No Date")


def _open_projects(user):
    return and_(projects.visible_filter(user), Project.archived_at.is_(None))


def my_open_tasks(s, user):
    """Unfinished tasks given to this user, in projects they can open (not archived)."""
    return s.scalars(select(Task).join(Project, Project.id == Task.project_id)
                     .where(Task.assignee_id == user.id, Task.status != DONE, _open_projects(user))
                     .options(*task_list.card_options()).order_by(*task_list.order())).all()


def group_of(task, day):
    if task.due_date is None:
        return "No Date"
    if task.due_date < day:
        return "Overdue"
    if task.due_date == day:
        return "Today"
    if task.due_date < day + timedelta(days=WEEK):
        return "This Week"
    return "Later"


def grouped(task_rows, day=None):
    """[(group name, [tasks])] in GROUPS order, empty groups left out."""
    day = day or today()
    groups = {name: [] for name in GROUPS}
    for task in task_rows:
        groups[group_of(task, day)].append(task)
    return [(name, rows) for name, rows in groups.items() if rows]


def waiting_for_review(s, user):
    """Tasks in review in projects where this user approves (Manager or owner)."""
    from . import permissions

    rows = s.scalars(select(Task).join(Project, Project.id == Task.project_id)
                     .where(Task.status == REVIEW, _open_projects(user))
                     .options(*task_list.card_options()).order_by(*task_list.order())).all()
    return [task for task in rows if permissions.at_least(permissions.effective_role(s, user, task.project), MANAGER)]


# ---------- The calendar ----------

@dataclass
class Day:
    day: date
    in_month: bool
    tasks: list = field(default_factory=list)
    deadlines: list = field(default_factory=list)  # projects due that day


def month_of(text):
    """'2026-11' -> (2026, 11); anything else -> this month."""
    try:
        year, month = (int(part) for part in (text or "").split("-"))
        date(year, month, 1)
        return year, month
    except ValueError:
        now = today()
        return now.year, now.month


def month_grid(year, month):
    """The weeks of the month, Monday first, including the days around it."""
    return month_calendar.Calendar(firstweekday=0).monthdatescalendar(year, month)


def calendar(s, user, year, month, project=None):
    """[[Day]] for the month. Without a project: the user's own tasks and the
    deadlines of their projects. With one: every task in that project."""
    weeks = month_grid(year, month)
    first, last = weeks[0][0], weeks[-1][-1]
    query = (select(Task).join(Project, Project.id == Task.project_id)
             .where(Task.due_date.between(first, last)).options(*task_list.card_options())
             .order_by(*task_list.order()))
    if project is not None:
        query = query.where(Task.project_id == project.id)
        due_projects = [project] if project.due_date and first <= project.due_date <= last else []
    else:
        query = query.where(Task.assignee_id == user.id, _open_projects(user))
        due_projects = s.scalars(select(Project).where(_open_projects(user),
                                                       Project.due_date.between(first, last))).all()
    days = {d: Day(d, d.month == month) for week in weeks for d in week}
    for task in s.scalars(query):
        days[task.due_date].tasks.append(task)
    for due in due_projects:
        days[due.due_date].deadlines.append(due)
    return [[days[d] for d in week] for week in weeks]


def next_and_previous(year, month):
    previous = (year - 1, 12) if month == 1 else (year, month - 1)
    following = (year + 1, 1) if month == 12 else (year, month + 1)
    return f"{previous[0]}-{previous[1]:02d}", f"{following[0]}-{following[1]:02d}"


# ---------- A project's list, with filters ----------

DUE_FILTERS = {"late": "Overdue", "week": "Due in 7 days", "none": "No deadline"}


def clean_filters(args, people, labels):
    """The filters from the address, keeping only values that make sense here."""
    filters = {}
    who = args.get("who", "")
    if who in ("me", "nobody") or (who.isdigit() and int(who) in {user.id for user in people}):
        filters["who"] = who
    label = args.get("label", "")
    if label.isdigit() and int(label) in {item.id for item in labels}:
        filters["label"] = label
    if args.get("priority") in PRIORITIES:
        filters["priority"] = args["priority"]
    if args.get("status") in STATUSES or args.get("status") == "open":
        filters["status"] = args["status"]
    if args.get("due") in DUE_FILTERS:
        filters["due"] = args["due"]
    return filters


def filtered(s, project, user, filters):
    day = today()
    query = select(Task).where(Task.project_id == project.id).options(*task_list.card_options())
    who = filters.get("who")
    if who == "me":
        query = query.where(Task.assignee_id == user.id)
    elif who == "nobody":
        query = query.where(Task.assignee_id.is_(None))
    elif who:
        query = query.where(Task.assignee_id == int(who))
    if "label" in filters:
        query = query.where(Task.id.in_(select(task_labels.c.task_id).where(
            task_labels.c.label_id == int(filters["label"]))))
    if "priority" in filters:
        query = query.where(Task.priority == filters["priority"])
    status = filters.get("status")
    if status == "open":
        query = query.where(Task.status != DONE)
    elif status:
        query = query.where(Task.status == status)
    due = filters.get("due")
    if due == "late":
        query = query.where(Task.due_date < day, Task.status != DONE)
    elif due == "week":
        query = query.where(Task.due_date.between(day, day + timedelta(days=WEEK - 1)))
    elif due == "none":
        query = query.where(Task.due_date.is_(None))
    rows = s.scalars(query.order_by(*task_list.order())).all()
    # Finished work last, so the list reads like a to-do list.
    return sorted(rows, key=lambda task: task.status == DONE)
