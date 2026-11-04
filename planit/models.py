"""The data model: every table, as Python classes (SQLAlchemy 2.0).

    users ──< team_members >── teams            (many-to-many: a Team is a group of people)
      │                          │
      │ owner_id                 └──< project_teams >──┐   (a Team shares a project, with one role)
      ▼                                                ▼
    projects ──< project_members >── users          (one person shares a project, with one role)
      │
      ├──< invites                                  (one-time links that add a person with a role)
      ├──< wip_limits                               (at most N tasks in a column)
      ├──< activity                                 (the project's history)
      ├──< labels >── task_labels ──< tasks         (many-to-many: "Bug", "Design")
      └──< tasks ── assignee_id, reporter_id ──> users
             ├──< checklist_items                   (small steps inside a task)
             └──< comments ── author_id ──> users

    notifications ── user_id ──> users              (someone's Inbox: mentions, reviews, ...)

A user is one login. Who may do what in a project is never stored on the
user: it comes from these links, and permissions.effective_role() picks the
highest one. The owner is projects.owner_id, so there is exactly one.
"""
from datetime import date, datetime

from sqlalchemy import (Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, String, Table, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .dates import utcnow
from .db import Base

# Roles in a project, lowest first. OWNER is never stored in a table: it is projects.owner_id.
VIEWER, MEMBER, MANAGER, OWNER = "viewer", "member", "manager", "owner"
ROLES = (VIEWER, MEMBER, MANAGER, OWNER)
RANK = {role: number for number, role in enumerate(ROLES)}
SHARED_ROLES = (VIEWER, MEMBER, MANAGER)  # what a person or a Team can be given
ROLE_RULE = "role IN ('viewer', 'member', 'manager')"

PERSONAL, TEAM = "personal", "team"
COLORS = ("blue", "teal", "green", "yellow", "orange", "red", "purple", "pink", "gray")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(40), unique=True)
    display_name: Mapped[str] = mapped_column(String(60))
    password_hash: Mapped[str] = mapped_column(String(255))
    # There is no email, so a forgotten password is reset with this code. It is
    # shown once and stored only as a hash, like a password.
    recovery_hash: Mapped[str | None] = mapped_column(String(255))
    # Each demo visitor gets their own user, deleted when it expires.
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    demo_expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Adding 1 logs this user out everywhere (load_user() compares it).
    session_version: Mapped[int] = mapped_column(Integer, default=1)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    @property
    def initial(self):
        return self.display_name[:1].upper()

    def __repr__(self):
        return f"<User {self.username}>"


# A plain many-to-many link: who is in which Team. Deleting either side deletes the link.
team_members = Table(
    "team_members", Base.metadata,
    Column("team_id", ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True),
)


class Team(Base):
    """A saved group of people (e.g. "Design Team"). Sharing a project with a
    Team gives everyone in it access at once; leaving the Team takes it away."""
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60))
    # The person who made it manages who is in it.
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    created_by: Mapped[User] = relationship()
    members: Mapped[list[User]] = relationship(secondary=team_members, order_by=User.display_name)


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (CheckConstraint("kind IN ('personal', 'team')", name="kind"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    # A short code that starts every task's number: WEB-12.
    key: Mapped[str] = mapped_column(String(5))
    description: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(10), default=PERSONAL)
    color: Mapped[str] = mapped_column(String(10), default="blue")
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    due_date: Mapped[date | None] = mapped_column(Date)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    # The number the next task gets (WEB-1, WEB-2, ...). Numbers are never reused.
    next_number: Mapped[int] = mapped_column(Integer, default=1)

    owner: Mapped[User] = relationship()
    members: Mapped[list["ProjectMember"]] = relationship(back_populates="project", cascade="all, delete-orphan",
                                                          passive_deletes=True)
    teams: Mapped[list["ProjectTeam"]] = relationship(back_populates="project", cascade="all, delete-orphan",
                                                      passive_deletes=True)

    @property
    def is_team(self):
        return self.kind == TEAM

    @property
    def is_archived(self):
        return self.archived_at is not None


class ProjectMember(Base):
    """One person shares a project, with one role. (The owner is not here.)"""
    __tablename__ = "project_members"
    __table_args__ = (CheckConstraint(ROLE_RULE, name="role"),)

    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True)
    role: Mapped[str] = mapped_column(String(10))
    added_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    project: Mapped[Project] = relationship(back_populates="members")
    user: Mapped[User] = relationship()


class ProjectTeam(Base):
    """A whole Team shares a project, with one role for everyone in it."""
    __tablename__ = "project_teams"
    __table_args__ = (CheckConstraint(ROLE_RULE, name="role"),)

    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True, index=True)
    role: Mapped[str] = mapped_column(String(10))
    added_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    project: Mapped[Project] = relationship(back_populates="teams")
    team: Mapped[Team] = relationship()


class Invite(Base):
    """A one-time link that adds whoever opens it to a project. Only a hash of
    the token is stored (invites.py)."""
    __tablename__ = "invites"
    __table_args__ = (CheckConstraint(ROLE_RULE, name="role"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(10))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime)
    used_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    project: Mapped[Project] = relationship()
    created_by: Mapped[User] = relationship(foreign_keys=[created_by_id])
    used_by: Mapped[User | None] = relationship(foreign_keys=[used_by_id])


# ---------- Tasks ----------

# The workflow's columns, in order. workflow.py says which moves are allowed.
BACKLOG, TODO, IN_PROGRESS, REVIEW, DONE = "backlog", "todo", "in_progress", "review", "done"
STATUSES = (BACKLOG, TODO, IN_PROGRESS, REVIEW, DONE)
STATUS_RULE = "status IN ('backlog', 'todo', 'in_progress', 'review', 'done')"

LOW, MEDIUM, HIGH, URGENT = "low", "medium", "high", "urgent"
PRIORITIES = (LOW, MEDIUM, HIGH, URGENT)


class Label(Base):
    """A coloured tag a project's tasks can have, like "Bug" or "Design"."""
    __tablename__ = "labels"
    __table_args__ = (UniqueConstraint("project_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(30))
    color: Mapped[str] = mapped_column(String(10), default="blue")


# Which task has which labels (many-to-many).
task_labels = Table(
    "task_labels", Base.metadata,
    Column("task_id", ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True),
    Column("label_id", ForeignKey("labels.id", ondelete="CASCADE"), primary_key=True, index=True),
)


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(STATUS_RULE, name="status"),
        CheckConstraint("priority IN ('low', 'medium', 'high', 'urgent')", name="priority"),
        # WEB-12 is unique inside its project.
        UniqueConstraint("project_id", "number"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(12), default=TODO)
    priority: Mapped[str] = mapped_column(String(8), default=MEDIUM, server_default=MEDIUM)
    # Deleting a person leaves their tasks unassigned, not deleted.
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    reporter_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    due_date: Mapped[date | None] = mapped_column(Date, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    project: Mapped[Project] = relationship()
    assignee: Mapped[User | None] = relationship(foreign_keys=[assignee_id])
    reporter: Mapped[User | None] = relationship(foreign_keys=[reporter_id])
    labels: Mapped[list[Label]] = relationship(secondary=task_labels, order_by=Label.name)
    checklist: Mapped[list["ChecklistItem"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", passive_deletes=True,
        order_by="ChecklistItem.position, ChecklistItem.id")
    comments: Mapped[list["Comment"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", passive_deletes=True, order_by="Comment.created_at")

    @property
    def key(self):
        return f"{self.project.key}-{self.number}"

    @property
    def is_done(self):
        return self.status == DONE

    @property
    def checked(self):
        """How many checklist items are ticked."""
        return sum(1 for item in self.checklist if item.done)


class ChecklistItem(Base):
    """One small step inside a task (a subtask), ticked when done."""
    __tablename__ = "checklist_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(String(200))
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    position: Mapped[int] = mapped_column(Integer, default=0)

    task: Mapped[Task] = relationship(back_populates="checklist")


class WipLimit(Base):
    """A Work in Progress limit: at most this many tasks in one column."""
    __tablename__ = "wip_limits"
    __table_args__ = (CheckConstraint(STATUS_RULE, name="status"), CheckConstraint("max_tasks > 0", name="positive"))

    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    status: Mapped[str] = mapped_column(String(12), primary_key=True)
    max_tasks: Mapped[int] = mapped_column(Integer)


class Activity(Base):
    """One line of a project's history: who did what to which task, and when.
    It outlives the task: a deleted task keeps its lines (task_id becomes NULL,
    and note still has its title)."""
    __tablename__ = "activity"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"), index=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    verb: Mapped[str] = mapped_column(String(20))  # created, moved, assigned, ... (activity.py)
    from_status: Mapped[str | None] = mapped_column(String(12))
    to_status: Mapped[str | None] = mapped_column(String(12))
    other_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    note: Mapped[str] = mapped_column(String(200), default="")  # the task's key and title at the time
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    project: Mapped[Project] = relationship()
    task: Mapped[Task | None] = relationship()
    actor: Mapped[User | None] = relationship(foreign_keys=[actor_id])
    other_user: Mapped[User | None] = relationship(foreign_keys=[other_user_id])


# ---------- Talking ----------

class Comment(Base):
    """Plain text, never HTML: the templates escape it (and mark @mentions)."""
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime)

    task: Mapped[Task] = relationship(back_populates="comments")
    author: Mapped[User | None] = relationship()


# What a notification is about (notify.py writes them, inbox.html says them).
MENTIONED, ASSIGNED_TO_YOU, REVIEW_ASKED, APPROVED, SENT_BACK, REOPENED, COMMENTED, ADDED = (
    "mentioned", "assigned", "review", "approved", "sent_back", "reopened", "commented", "added")


class Notification(Base):
    """One line in someone's Inbox."""
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    comment_id: Mapped[int | None] = mapped_column(ForeignKey("comments.id", ondelete="SET NULL"))
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    read_at: Mapped[datetime | None] = mapped_column(DateTime)

    project: Mapped[Project] = relationship()
    task: Mapped[Task | None] = relationship()
    comment: Mapped[Comment | None] = relationship()
    actor: Mapped[User | None] = relationship(foreign_keys=[actor_id])
