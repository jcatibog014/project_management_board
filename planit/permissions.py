"""EVERY rule about who may do what lives here.

A person's role in a project is the HIGHEST of:
  - the owner (projects.owner_id),
  - the role they were given themselves (project_members),
  - the role of each Team they are in that shares the project (project_teams).

effective_role() works it out once per request. Views put it in an Access,
and then ask the plain can_...() functions below. Views and templates never
compare roles themselves, so tests/test_permissions.py can check every rule
as a table of role x action.

An archived project is read-only for everyone; only its owner can bring it back.
"""
from dataclasses import dataclass

from flask import g, has_request_context
from sqlalchemy import select

from .models import MANAGER, MEMBER, OWNER, RANK, SHARED_ROLES, Project, ProjectMember, ProjectTeam, User, \
    team_members


def highest(roles):
    roles = [role for role in roles if role]
    return max(roles, key=RANK.__getitem__) if roles else None


def at_least(role, lowest):
    return role is not None and RANK[role] >= RANK[lowest]


def stored_role(s, user, project):
    """The role from the database alone (owner, own role, Teams)."""
    if user is None:
        return None
    if project.owner_id == user.id:
        return OWNER
    direct = s.scalar(select(ProjectMember.role).where(ProjectMember.project_id == project.id,
                                                       ProjectMember.user_id == user.id))
    via_teams = s.scalars(
        select(ProjectTeam.role)
        .join(team_members, team_members.c.team_id == ProjectTeam.team_id)
        .where(ProjectTeam.project_id == project.id, team_members.c.user_id == user.id)).all()
    return highest([direct, *via_teams])


def effective_role(s, user, project):
    """What this user may do in this project, or None if they can't see it.
    Remembered for the rest of the request."""
    if user is None:
        return None
    cache = g.setdefault("roles", {}) if has_request_context() else {}
    key = (user.id, project.id)
    if key not in cache:
        role = stored_role(s, user, project)
        # The demo's "View As" choice (Settings) plays a role in its team projects.
        view_as = getattr(g, "view_as", None) if has_request_context() else None
        if role and view_as and user.is_demo and project.is_team:
            role = view_as
        cache[key] = role
    return cache[key]


@dataclass(frozen=True)
class Access:
    """Who is looking at which project, and their role in it."""
    user: User | None
    project: Project
    role: str | None

    @property
    def archived(self):
        return self.project.is_archived

    @property
    def writable(self):
        """Archived projects are read-only for everyone."""
        return self.role is not None and not self.archived

    def at_least(self, lowest):
        return at_least(self.role, lowest)


def access_for(s, user, project):
    return Access(user, project, effective_role(s, user, project))


# ---------- Projects ----------

def can_view_project(access):
    return access.role is not None


def can_edit_project(access):
    """Rename it, change its colour, description and deadline."""
    return access.writable and access.at_least(MANAGER)


def is_owner(access):
    """Archive, delete, transfer ownership, switch Personal <-> Team."""
    return access.role == OWNER and access.user is not None and access.user.id == access.project.owner_id


def can_archive_project(access):
    return is_owner(access)


def can_leave_project(access):
    """Anyone but the owner can leave a project they were added to (Teams are left on the Team page)."""
    return access.role is not None and access.role != OWNER


# ---------- People ----------

def can_manage_people(access):
    """Add and remove people, Teams and invite links. Personal projects have nobody to manage."""
    return access.writable and access.project.is_team and access.at_least(MANAGER)


def roles_you_can_give(access):
    """The owner can make Managers; a Manager can only give the roles below their own."""
    if not can_manage_people(access):
        return ()
    if access.role == OWNER:
        return SHARED_ROLES
    return tuple(role for role in SHARED_ROLES if RANK[role] < RANK[access.role])


def can_change_role(access, current_role):
    """Change or remove someone whose role (from this one link) is current_role.
    A Manager can't touch another Manager: only the owner can."""
    return can_manage_people(access) and (access.role == OWNER or RANK[current_role] < RANK[access.role])


def can_give_role(access, role):
    return role in roles_you_can_give(access)


# ---------- Teams (the saved groups) ----------

def can_manage_team(user, team):
    """Only the person who made a Team adds and removes its people."""
    return user is not None and team.created_by_id == user.id


def can_view_team(user, team):
    return user is not None and (can_manage_team(user, team) or any(member.id == user.id for member in team.members))
