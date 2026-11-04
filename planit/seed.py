"""The demo's sample company, "Orbit Labs": teammates, Teams, projects and tasks.

Every demo visitor gets their own copy (auth.start_demo), so nothing they do
reaches anyone else. The sample teammates are demo users too: they can't log
in, and they are deleted with the demo.

The visitor plays a different role in each project, so every role can be seen:
    Website Revamp      Team project, the visitor is the Owner
    Mobile App Launch   Team project, a Member through the Dev Team
    Marketing Plan      Team project, a Viewer
    Learn Flask         Personal project

Every page the demo can open must show an example: add sample data here with
every new feature (tests/test_demo.py checks each page).
"""
import secrets
from datetime import timedelta

from werkzeug.security import generate_password_hash

from . import activity
from .dates import to_local
from .models import BACKLOG, DONE, IN_PROGRESS, MANAGER, MEMBER, PERSONAL, REVIEW, TEAM, TODO, VIEWER, \
    ChecklistItem, Comment, Label, Notification, Project, ProjectMember, ProjectTeam, Task, Team, User, WipLimit

TEAMMATES = [
    ("ana", "Ana Cruz"), ("ben", "Ben Santos"), ("cara", "Cara Lim"), ("dev", "Dev Patel"), ("eli", "Eli Reyes"),
]


class World:
    """Builds the sample company for one demo user, at one moment."""

    def __init__(self, s, user, now):
        self.s, self.user, self.now = s, user, now
        self.today = to_local(now).date()
        self.people = {"me": user}
        self.labels = {}

    # ---------- People and Teams ----------

    def teammates(self):
        # The visitor is demo-<tag>-sam; the teammates share the tag. (A practice
        # login without a tag, docs/make_practice_data.py, uses its own name.)
        parts = self.user.username.split("-")
        tag = parts[1] if len(parts) > 2 else self.user.username
        for short, name in TEAMMATES:
            # Nobody knows this password, and demo users can't log in anyway.
            mate = User(username=f"demo-{tag}-{short}", display_name=name, is_demo=True,
                        demo_expires_at=self.user.demo_expires_at,
                        password_hash=generate_password_hash(secrets.token_urlsafe(16)))
            self.s.add(mate)
            self.people[short] = mate
        self.s.flush()

    def team(self, name, maker, members):
        team = Team(name=name, created_by_id=self.people[maker].id, created_at=self.ago(days=40))
        team.members = [self.people[m] for m in members]
        self.s.add(team)
        self.s.flush()
        return team

    # ---------- Projects ----------

    def project(self, name, key, owner, color, kind=TEAM, description="", due_in=None, people=None, teams=None,
                labels=(("Bug", "red"), ("Feature", "blue"), ("Design", "purple"))):
        project = Project(name=name, key=key, kind=kind, color=color, owner_id=self.people[owner].id,
                          description=description, created_at=self.ago(days=60),
                          due_date=self.today + timedelta(days=due_in) if due_in is not None else None)
        self.s.add(project)
        self.s.flush()
        for short, role in (people or {}).items():
            self.s.add(ProjectMember(project_id=project.id, user_id=self.people[short].id, role=role))
        for team, role in (teams or {}).items():
            self.s.add(ProjectTeam(project_id=project.id, team_id=team.id, role=role))
        for label_name, label_color in labels:
            label = Label(project_id=project.id, name=label_name, color=label_color)
            self.s.add(label)
            self.labels[(project.id, label_name)] = label
        self.s.flush()
        return project

    def task(self, project, title, status=TODO, who=None, by="me", due_in=None, priority="medium", labels=(),
             steps=(), description="", age=20, finished=None):
        """A task with a believable history. age: days since it was made.
        finished: days ago it was approved (for Done)."""
        made = self.ago(days=age, hours=3)
        task = Task(project_id=project.id, project=project, number=project.next_number, title=title,
                    description=description, status=status, priority=priority, reporter_id=self.people[by].id,
                    assignee_id=self.people[who].id if who else None, created_at=made, updated_at=made,
                    due_date=self.today + timedelta(days=due_in) if due_in is not None else None)
        project.next_number += 1
        task.labels = [self.labels[(project.id, name)] for name in labels]
        for position, (text, done) in enumerate(steps, start=1):
            task.checklist.append(ChecklistItem(text=text, done=done, position=position))
        self.s.add(task)
        self.s.flush()
        self.log(project, by, activity.CREATED, task, made, to_status=TODO if status != BACKLOG else BACKLOG)
        if who:
            self.log(project, by, activity.ASSIGNED, task, made + timedelta(hours=1), other_user_id=self.people[who].id)
        path = {TODO: [], IN_PROGRESS: [IN_PROGRESS], REVIEW: [IN_PROGRESS, REVIEW],
                DONE: [IN_PROGRESS, REVIEW, DONE]}.get(status, [])
        before = TODO
        end = self.ago(days=finished) if finished is not None else self.ago(hours=5)
        for step, to in enumerate(path, start=1):
            moment = made + (end - made) * step / len(path)
            actor = (who or by) if to != DONE else project_manager(project, self)
            self.log(project, actor, activity.verb_for_move(before, to), task, moment, from_status=before,
                     to_status=to)
            before = to
            task.updated_at = moment
        if status == DONE:
            task.completed_at = end
        return task

    def comment(self, task, author, body, hours):
        moment = self.ago(hours=hours)
        comment = Comment(task_id=task.id, author_id=self.people[author].id, body=body, created_at=moment)
        task.comments.append(comment)
        self.s.flush()
        self.log(task.project, author, activity.COMMENTED, task, moment)
        return comment

    def note(self, kind, actor, project, task, comment, hours, read=False):
        moment = self.ago(hours=hours)
        self.s.add(Notification(user_id=self.user.id, kind=kind, project_id=project.id,
                                task_id=task.id if task else None, comment_id=comment.id if comment else None,
                                actor_id=self.people[actor].id, created_at=moment, read_at=moment if read else None))

    def log(self, project, actor, verb, task, moment, **fields):
        entry = activity.log(self.s, project, self.people[actor], verb, task, **fields)
        entry.created_at = moment
        return entry

    def ago(self, days=0, hours=0):
        return self.now - timedelta(days=days, hours=hours)


def project_manager(project, world):
    """Who approves in this project: its owner."""
    return next(short for short, user in world.people.items() if user.id == project.owner_id)


def build(s, user, now):
    """Fill the demo user's world. The caller commits."""
    w = World(s, user, now)
    w.teammates()
    design = w.team("Design Team", "me", ["me", "ana", "ben"])
    dev_team = w.team("Dev Team", "dev", ["dev", "eli", "cara", "me"])

    # ----- Website Revamp: the visitor owns it -----
    web = w.project("Website Revamp", "WEB", "me", "blue", due_in=24,
                    description="A fresh look for the Orbit Labs website, live before the December launch.",
                    people={"cara": MANAGER, "eli": VIEWER}, teams={design: MEMBER})
    s.add(WipLimit(project_id=web.id, status=IN_PROGRESS, max_tasks=3))
    w.task(web, "Write the new homepage copy", BACKLOG, by="ana", labels=["Feature"], age=12)
    w.task(web, "Collect customer quotes", BACKLOG, due_in=12, by="cara", age=9)
    login_page = w.task(web, "Design the login page", TODO, due_in=-1, priority="high", labels=["Design"], by="ana", age=8,
           description="Match the new brand colours. Keep **one** big button and a link to sign up.")
    w.task(web, "Pick the colour palette", TODO, "ana", due_in=2, labels=["Design"], age=6,
           steps=[("Collect three options", True), ("Check contrast", False), ("Ask the team", False)])
    nav = w.task(web, "Build the navigation bar", IN_PROGRESS, "me", due_in=1, priority="high", labels=["Feature"],
           age=10, steps=[("Desktop menu", True), ("Phone menu", True), ("Keyboard support", False)],
           description="The menu at the top of every page.\n\n- Logo on the left\n- Five links\n- A search button")
    w.task(web, "Set up the contact form", IN_PROGRESS, "ana", due_in=5, labels=["Feature"], age=7)
    w.task(web, "Fix the broken footer links", IN_PROGRESS, "ben", due_in=0, priority="urgent", labels=["Bug"],
           age=3, by="cara")
    speed = w.task(web, "Make pages load faster", REVIEW, "cara", due_in=3, labels=["Feature"], age=14,
           steps=[("Smaller pictures", True), ("Cache the fonts", True)])
    w.task(web, "Choose the new logo", DONE, "ana", labels=["Design"], age=30, finished=18)
    w.task(web, "Move the domain to the new host", DONE, "me", age=40, finished=33)
    w.task(web, "Write the style guide", DONE, "ben", labels=["Design"], age=25, finished=10)
    w.task(web, "Plan the site map", DONE, "cara", age=50, finished=44)
    w.task(web, "Test on old phones", DONE, "ana", labels=["Bug"], age=12, finished=4)

    # ----- Mobile App Launch: the visitor is a Member through the Dev Team -----
    app = w.project("Mobile App Launch", "APP", "dev", "teal", due_in=40,
                    description="Version 1.0 of the Orbit Labs app for Android and iPhone.",
                    people={"eli": MANAGER}, teams={dev_team: MEMBER})
    w.task(app, "Write the store description", BACKLOG, by="eli", age=5)
    w.task(app, "Add dark mode", TODO, by="cara", labels=["Feature"], age=4)
    sign_in = w.task(app, "Sign-in with a code", TODO, "me", due_in=6, labels=["Feature"], by="eli", age=6)
    crash = w.task(app, "Crash when opening settings", IN_PROGRESS, "me", due_in=-2, priority="urgent", labels=["Bug"],
           by="eli", age=4, steps=[("Find the cause", True), ("Write a fix", False), ("Test on Android", False)])
    w.task(app, "Push notifications", IN_PROGRESS, "cara", due_in=8, labels=["Feature"], by="dev", age=9)
    icon = w.task(app, "App icon in all sizes", REVIEW, "me", due_in=1, labels=["Design"], by="dev", age=11)
    w.task(app, "Set up the test phones", DONE, "eli", age=35, finished=27)
    w.task(app, "Offline mode", DONE, "dev", labels=["Feature"], age=28, finished=12)
    login_screen = w.task(app, "Login screen", DONE, "me", labels=["Feature"], by="eli", age=20, finished=8)
    w.task(app, "Speed up the start", DONE, "cara", age=16, finished=2)

    # ----- Marketing Plan: the visitor can only look and comment -----
    marketing = w.project("Marketing Plan", "MKT", "cara", "orange", due_in=55,
                          description="How we tell people about the launch.",
                          people={"me": VIEWER, "ana": MEMBER, "ben": MANAGER},
                          labels=(("Social", "pink"), ("Email", "teal"), ("Event", "yellow")))
    w.task(marketing, "Launch video script", TODO, "ana", due_in=9, labels=["Social"], by="cara", age=6)
    w.task(marketing, "Newsletter for December", IN_PROGRESS, "ben", due_in=4, labels=["Email"], by="cara", age=8)
    venue = w.task(marketing, "Book the launch party venue", REVIEW, "cara", due_in=-3, priority="high",
           labels=["Event"], by="cara", age=13)
    w.task(marketing, "Logo stickers", DONE, "ana", labels=["Event"], by="cara", age=30, finished=15)

    # ----- Learn Flask: personal -----
    flask_project = w.project("Learn Flask", "LF", "me", "green", kind=PERSONAL,
                              description="My own study plan, one small app at a time.",
                              labels=(("Reading", "gray"), ("Practice", "green")))
    w.task(flask_project, "Read about blueprints", TODO, "me", labels=["Reading"], age=5,
           steps=[("Flask docs", True), ("Make a small example", False)])
    w.task(flask_project, "Build a to-do app", IN_PROGRESS, "me", due_in=3, labels=["Practice"], age=7,
           steps=[("Routes", True), ("Templates", True), ("Database", False), ("Tests", False)])
    w.task(flask_project, "Try SQLAlchemy relationships", BACKLOG, labels=["Reading"], age=2)
    w.task(flask_project, "Finish the tutorial", DONE, "me", labels=["Practice"], age=21, finished=14)
    s.flush()

    # ----- Talking: comments with @mentions, and the Inbox they fill -----
    w.comment(nav, "ana", "Can we keep the search button on phones too? @sam", hours=30)
    w.comment(nav, "me", "Yes, it goes next to the menu button. @ana can you check the spacing?", hours=26)
    w.comment(nav, "ana", "Looks good on my phone now.", hours=6)
    hi = w.comment(speed, "cara", "Pictures are now half the size. Ready for review, @sam!", hours=20)
    w.comment(login_page, "ana", "I made two versions. Which one do we like?", hours=50)
    crash_note = w.comment(crash, "eli", "@sam this is the top bug for the release. Can you look today?", hours=4)
    w.comment(crash, "me", "On it. It only happens when the app has no internet.", hours=3)
    w.comment(icon, "dev", "The round Android icon looks a bit small.", hours=10)
    w.comment(venue, "ben", "The hall on 5th Street is free on the 12th.", hours=28)
    w.comment(venue, "cara", "Let's book it. @ana please send the deposit.", hours=22)
    w.note("mentioned", "eli", app, crash, crash_note, hours=4)
    w.note("review", "cara", web, speed, None, hours=19)
    w.note("mentioned", "cara", web, speed, hi, hours=20)
    w.note("assigned", "eli", app, sign_in, None, hours=30)
    w.note("approved", "dev", app, login_screen, None, hours=8 * 24, read=True)
    w.note("commented", "ana", web, nav, None, hours=6, read=True)
    w.note("added", "cara", marketing, None, None, hours=20 * 24, read=True)
    return w
