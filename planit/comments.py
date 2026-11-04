"""Comments on tasks, and @mentions in them.

A mention is "@" and someone's handle: their username. Sample demo
teammates have long usernames (demo-abc123-ana), so their handle is the
short last part (@ana). Only people who can open the project can be mentioned.
"""
import re

from markupsafe import Markup, escape

from . import activity, notify, projects
from .dates import utcnow
from .models import COMMENTED, MENTIONED, Comment

BODY_MAX_LENGTH = 4000
MENTION = re.compile(r"(?<![\w@])@([a-z0-9_-]{2,40})", re.IGNORECASE)


def handle(user):
    if user.is_demo and user.username.count("-") >= 2:
        return user.username.rsplit("-", 1)[1]
    return user.username


def handles(s, project):
    """{handle: user} for everyone who can open the project."""
    return {handle(person.user): person.user for person in projects.people(s, project)}


def clean_body(text):
    """(body, problem)"""
    body = (text or "").replace("\r\n", "\n").strip()
    if not body:
        return body, "Write something first."
    if len(body) > BODY_MAX_LENGTH:
        return body, f"Use at most {BODY_MAX_LENGTH:,} characters."
    return body, None


def mentioned(body, known):
    return [known[name.lower()] for name in MENTION.findall(body) if name.lower() in known]


def add(s, task, author, body):
    """Save the comment, write the history and tell the right people. The caller commits."""
    comment = Comment(task_id=task.id, author_id=author.id, body=body, created_at=utcnow())
    task.comments.append(comment)
    s.flush()
    activity.log(s, task.project, author, activity.COMMENTED, task)
    known = handles(s, task.project)
    told = notify.send(s, mentioned(body, known), MENTIONED, author, task.project, task, comment)
    # The people the task belongs to hear about it too, unless they were just mentioned.
    others = [user for user in (task.assignee, task.reporter) if user and user.id not in told]
    notify.send(s, others, COMMENTED, author, task.project, task, comment)
    return comment


def with_mentions(body, known):
    """The comment as safe HTML: everything escaped, known @handles marked."""
    def mark(match):
        name = match.group(1)
        if name.lower() not in known:
            return match.group(0)
        return f'<span class="mention" title="{escape(known[name.lower()].display_name)}">@{name}</span>'

    return Markup(MENTION.sub(mark, str(escape(body))))
