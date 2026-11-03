"""Projects and the people who share them.

Views call these functions after checking permissions.py. They change the
session but never commit: the view does, once everything worked.
"""
import re
from dataclasses import dataclass, field

from sqlalchemy import or_, select

from . import permissions
from .models import COLORS, MEMBER, OWNER, PERSONAL, RANK, SHARED_ROLES, TEAM, Project, ProjectMember, \
    ProjectTeam, Team, User, team_members

NAME_MAX_LENGTH = 80
DESCRIPTION_MAX_LENGTH = 2000
KEY_PATTERN = re.compile(r"[A-Z][A-Z0-9]{1,4}")


# ---------- Which projects can someone see? ----------

def visible_filter(user):
    """A WHERE clause: the projects this user owns, was added to, or shares through a Team."""
    own_role = select(ProjectMember.project_id).where(ProjectMember.user_id == user.id)
    via_team = (select(ProjectTeam.project_id)
                .join(team_members, team_members.c.team_id == ProjectTeam.team_id)
                .where(team_members.c.user_id == user.id))
    return or_(Project.owner_id == user.id, Project.id.in_(own_role), Project.id.in_(via_team))


def visible(s, user, archived=False):
    archived_rule = Project.archived_at.is_not(None) if archived else Project.archived_at.is_(None)
    return s.scalars(select(Project).where(visible_filter(user), archived_rule)
                     .order_by(Project.name)).all()


# ---------- Making and changing a project ----------

def suggest_key(name):
    """'Website Revamp' -> 'WR', 'Marketing' -> 'MAR'."""
    words = re.findall(r"[A-Za-z0-9]+", name)
    if not words:
        return "PRJ"
    key = "".join(word[0] for word in words[:4]) if len(words) > 1 else words[0][:3]
    key = key.upper()
    if not key[0].isalpha():
        key = "P" + key
    return (key + "X")[:5] if len(key) < 2 else key[:5]


def clean_form(form):
    """(values, errors) from the New Project or Project Settings form."""
    values = {
        "name": form.get("name", "").strip(),
        "key": form.get("key", "").strip().upper(),
        "description": form.get("description", "").replace("\r\n", "\n").strip(),
        "color": form.get("color", "blue"),
        "due_date": form.get("due_date", "").strip(),
    }
    errors = {}
    if not values["name"] or len(values["name"]) > NAME_MAX_LENGTH:
        errors["name"] = f"Use 1 to {NAME_MAX_LENGTH} characters."
    if not values["key"]:
        values["key"] = suggest_key(values["name"])
    if not KEY_PATTERN.fullmatch(values["key"]):
        errors["key"] = "Use 2 to 5 capital letters or numbers, starting with a letter."
    if len(values["description"]) > DESCRIPTION_MAX_LENGTH:
        errors["description"] = f"Use at most {DESCRIPTION_MAX_LENGTH:,} characters."
    if values["color"] not in COLORS:
        values["color"] = "blue"
    values["due_date"], problem = parse_date(values["due_date"])
    if problem:
        errors["due_date"] = problem
    return values, errors


def parse_date(text):
    """(date or None, problem or None) from a <input type="date"> value."""
    from datetime import date

    if not text:
        return None, None
    try:
        return date.fromisoformat(text), None
    except ValueError:
        return None, "Use a date like 2026-12-31."


def create(s, owner, values, kind=PERSONAL):
    project = Project(owner_id=owner.id, kind=kind if kind in (PERSONAL, TEAM) else PERSONAL, **values)
    s.add(project)
    s.flush()
    return project


# ---------- People ----------

@dataclass
class Person:
    """One row of the Members page: a person, their best role, and where it comes from."""
    user: User
    role: str
    direct_role: str | None = None  # their own role, if they were added themselves
    teams: list = field(default_factory=list)  # [(Team, role)] that bring them in

    @property
    def is_owner(self):
        return self.role == OWNER


def people(s, project):
    """Everyone who can open this project, owner first, then by role and name."""
    found = {project.owner_id: Person(project.owner, OWNER)}
    for link in s.scalars(select(ProjectMember).where(ProjectMember.project_id == project.id)):
        person = found.setdefault(link.user_id, Person(link.user, link.role))
        person.direct_role = link.role
        person.role = permissions.highest([person.role, link.role])
    rows = s.execute(
        select(User, Team, ProjectTeam.role)
        .join(team_members, team_members.c.user_id == User.id)
        .join(Team, Team.id == team_members.c.team_id)
        .join(ProjectTeam, ProjectTeam.team_id == Team.id)
        .where(ProjectTeam.project_id == project.id)).all()
    for user, team, role in rows:
        person = found.setdefault(user.id, Person(user, role))
        person.teams.append((team, role))
        person.role = permissions.highest([person.role, role])
    return sorted(found.values(), key=lambda p: (-RANK[p.role], p.user.display_name.lower()))


def assignable(s, project):
    """People a task can be given to: everyone who can work on it (Member or more)."""
    return [person.user for person in people(s, project) if RANK[person.role] >= RANK[MEMBER]]


def find_user(s, username):
    return s.scalar(select(User).where(User.username == username.strip().lower(), User.is_demo.is_(False)))


def add_person(s, project, user, role):
    """Give this person their own role (or raise the one they have). Returns a message."""
    if user.id == project.owner_id:
        return f"{user.display_name} owns this project."
    link = s.get(ProjectMember, (project.id, user.id))
    if link is None:
        s.add(ProjectMember(project_id=project.id, user_id=user.id, role=role))
        return f"{user.display_name} was added as {role.title()}."
    link.role = role
    return f"{user.display_name} is now {role.title()}."


def add_team(s, project, team, role):
    link = s.get(ProjectTeam, (project.id, team.id))
    if link is None:
        s.add(ProjectTeam(project_id=project.id, team_id=team.id, role=role))
        return f"{team.name} was added as {role.title()}. Everyone in it can open the project now."
    link.role = role
    return f"{team.name} is now {role.title()}."


def transfer(s, project, new_owner):
    """The new owner leaves their own row; the old owner stays on as a Manager."""
    old_owner_id = project.owner_id
    link = s.get(ProjectMember, (project.id, new_owner.id))
    if link is not None:
        s.delete(link)
    project.owner_id = new_owner.id
    s.add(ProjectMember(project_id=project.id, user_id=old_owner_id, role="manager"))


def has_others(project):
    """Anyone besides the owner? A Team project with people can't become Personal."""
    return bool(project.members or project.teams)


def role_choices(roles):
    return [(role, role.title()) for role in roles]


SHARED_ROLE_CHOICES = role_choices(SHARED_ROLES)
