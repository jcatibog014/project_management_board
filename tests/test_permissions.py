"""Every rule in permissions.py as a table: each role against each action.

The rules are plain functions of an Access (who, which project, which role),
so these tests need no database. The route tests in test_projects.py check
that the views really ask them.
"""
from types import SimpleNamespace

import pytest

from planit import permissions as can
from planit.models import MANAGER, MEMBER, OWNER, VIEWER

ROLES = [OWNER, MANAGER, MEMBER, VIEWER, None]  # None: not in the project
ME, OWNER_ID = 1, 1


def access(role, kind="team", archived=False):
    project = SimpleNamespace(id=10, owner_id=OWNER_ID if role == OWNER else 99, is_team=kind == "team",
                              is_archived=archived)
    return can.Access(SimpleNamespace(id=ME, is_demo=False), project, role)


def row(rule, expected, **project):
    """[(role, expected answer)] for one action."""
    return [(role, rule, answer, project) for role, answer in zip(ROLES, expected)]


#           action                          Owner  Manager Member Viewer Outsider
TABLE = [
    *row(can.can_view_project,             [True,  True,   True,  True,  False]),
    *row(can.can_edit_project,             [True,  True,   False, False, False]),
    *row(can.is_owner,                     [True,  False,  False, False, False]),
    *row(can.can_archive_project,          [True,  False,  False, False, False]),
    *row(can.can_leave_project,            [False, True,   True,  True,  False]),
    *row(can.can_manage_people,            [True,  True,   False, False, False]),
    # Personal projects have nobody to manage.
    *row(can.can_manage_people,            [False, False,  False, False, False], kind="personal"),
    # Archived projects are read-only for everyone...
    *row(can.can_edit_project,             [False, False,  False, False, False], archived=True),
    *row(can.can_manage_people,            [False, False,  False, False, False], archived=True),
    # ...but can still be seen, and the owner can still bring them back.
    *row(can.can_view_project,             [True,  True,   True,  True,  False], archived=True),
    *row(can.can_archive_project,          [True,  False,  False, False, False], archived=True),
]


@pytest.mark.parametrize("role, rule, expected, project", TABLE,
                         ids=[f"{rule.__name__}-{role}-{project or 'team'}" for role, rule, expected, project in TABLE])
def test_rule(role, rule, expected, project):
    assert rule(access(role, **project)) is expected


@pytest.mark.parametrize("role, gives", [
    (OWNER, (VIEWER, MEMBER, MANAGER)),
    (MANAGER, (VIEWER, MEMBER)),  # only roles below their own
    (MEMBER, ()),
    (VIEWER, ()),
])
def test_roles_each_role_can_give(role, gives):
    assert can.roles_you_can_give(access(role)) == gives


@pytest.mark.parametrize("role, target, allowed", [
    (OWNER, MANAGER, True), (OWNER, MEMBER, True),
    (MANAGER, MANAGER, False),  # a Manager can't change or remove another Manager
    (MANAGER, MEMBER, True), (MANAGER, VIEWER, True),
    (MEMBER, VIEWER, False),
])
def test_who_can_change_whom(role, target, allowed):
    assert can.can_change_role(access(role), target) is allowed


def test_the_highest_role_wins():
    assert can.highest([VIEWER, MANAGER, MEMBER]) == MANAGER
    assert can.highest([None, VIEWER]) == VIEWER
    assert can.highest([]) is None


def test_team_rules():
    maker, member, stranger = (SimpleNamespace(id=n) for n in (1, 2, 3))
    team = SimpleNamespace(created_by_id=1, members=[maker, member])
    assert can.can_manage_team(maker, team) and not can.can_manage_team(member, team)
    assert can.can_view_team(member, team) and not can.can_view_team(stranger, team)
