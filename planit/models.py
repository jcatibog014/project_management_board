"""The data model: every table, as Python classes (SQLAlchemy 2.0).

    users

A user is one login. Who may do what in a project comes later, from the
people and Teams the project is shared with (see permissions.py).
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .dates import utcnow
from .db import Base


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
