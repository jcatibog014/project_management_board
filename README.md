# Plan-It

**Your projects, in orbit.**

Plan-It is a project board. You make projects and add tasks. Tasks move from
**Backlog** to **Done**. You can work alone, or with a team. Every person in a
project has a **role**, and the role says what they can do.

I made this app to practise **roles, relationships, permissions and workflows**.

![The board](docs/screenshots/board.png)

## Try It

Press **Try demo** on the login page. You get your own sample company, "Orbit Labs".
You are **Sam Rivera**. Nobody else sees your demo, and it is deleted after 24 hours.

In the demo you have a different role in each project:

| Project | Kind | Your role |
|---|---|---|
| Website Revamp | Team | Owner |
| Mobile App Launch | Team | Member (through the Dev Team) |
| Marketing Plan | Team | Viewer |
| Learn Flask | Personal | Owner |

Use **View As** (at the bottom of the menu) to see a project as a Manager, a Member or a Viewer.

![Log in](docs/screenshots/login.png)

## What It Can Do

### Projects

- A project is **Personal** (only you) or **Team** (shared).
- Each project has a short **key**, like `WEB`. Tasks are numbered `WEB-1`, `WEB-2` ...
- Give a project a colour, a description and a deadline.
- Archive a project when it is finished. Then it is read-only.

| Projects | New project |
|---|---|
| ![Projects](docs/screenshots/projects.png) | ![New project](docs/screenshots/new-project.png) |

### Roles

There are four roles in a project:

| Role | What the person can do |
|---|---|
| **Owner** | Everything. Only the owner can archive, delete or give away the project. |
| **Manager** | Add and remove people, edit any task, approve work in review. |
| **Member** | Add tasks, and work on the tasks given to them. |
| **Viewer** | Look at everything and write comments. |

- Add a person by their username, or send an **invite link** (it works one time, for 7 days).
- A **Team** is a group of people, like "Design Team". Add a Team to a project, and everyone in the Team can join in.
- If a person has two roles (their own and one from a Team), the **higher role wins**.
- Take someone out of a Team, and they lose the projects that the Team gave them.

| Members | Teams |
|---|---|
| ![Members](docs/screenshots/members.png) | ![Teams](docs/screenshots/teams.png) |

### The Workflow

Every task moves through five columns:

**Backlog** -> **To Do** -> **In Progress** -> **In Review** -> **Done**

The rules:

- A task moves one step at a time. It can also go one step back.
- A task needs a person before work can start.
- A **Member** can only move their own tasks.
- Only a **Manager** or the **Owner** can approve a task (In Review -> Done), or open a Done task again.
- A column can have a **limit** (for example: at most 3 tasks In Progress).
- Drag a card to move it, or use the card's menu.
- The app says **why** when you can't move a task.

| A Member's board | A Viewer looks at a task |
|---|---|
| ![A Member's board](docs/screenshots/member-board.png) | ![View As a Viewer](docs/screenshots/view-as-viewer.png) |

### Tasks

- A title, a description (you can use Markdown), a person, a deadline and a priority (Low, Medium, High, Urgent).
- **Labels**, like Bug or Design.
- A **checklist** of small steps.
- **Comments**. Write `@` and a name to tell someone.
- A **history** of every change.

| A task | Comments |
|---|---|
| ![A task](docs/screenshots/task.png) | ![Comments](docs/screenshots/comments.png) |

### Planning

- **Home**: what is late, what is due today and this week, and what is new.
- **My Tasks**: all your tasks from every project, sorted by deadline.
- **Calendar**: your deadlines on a month page. Every project has its own calendar too.
- **List**: a project's tasks with filters (person, status, label, priority, deadline).
- **Inbox**: when someone writes `@you`, gives you a task, or asks for your review.

| Home | My Tasks |
|---|---|
| ![Home](docs/screenshots/home.png) | ![My Tasks](docs/screenshots/my-tasks.png) |

| Calendar | List with filters |
|---|---|
| ![Calendar](docs/screenshots/calendar.png) | ![List](docs/screenshots/list.png) |

| Inbox | Activity |
|---|---|
| ![Inbox](docs/screenshots/inbox.png) | ![Activity](docs/screenshots/activity.png) |

### Dashboard

Every project has a dashboard: how much is done, tasks in each column, tasks
finished each week, and how much work each person has. You can open every
chart as a table.

| Dashboard | Dashboard (dark) |
|---|---|
| ![Dashboard](docs/screenshots/dashboard.png) | ![Dashboard in dark mode](docs/screenshots/dashboard-dark.png) |

### Settings

Choose light or dark mode, change your name and password, and make a new
recovery code. There is no email, so you get a **recovery code** when you sign
up. Keep it: you need it if you forget your password.

| Settings | Project settings |
|---|---|
| ![Settings](docs/screenshots/settings.png) | ![Project settings](docs/screenshots/project-settings.png) |

| Dark mode | Phone |
|---|---|
| ![The board in dark mode](docs/screenshots/board-dark.png) | ![The board on a phone](docs/screenshots/phone.png) |

## Tools

| Tool | What it is | What I use it for |
|---|---|---|
| **Python** | A programming language | All the code on the server |
| **Flask** | A small web framework for Python | Pages, forms and links |
| **SQLAlchemy** | A tool to use a database from Python | The tables: users, projects, tasks, roles ... |
| **Alembic** | Database migrations | Changing the tables without losing data |
| **SQLite** | A small database in one file | The database on my computer and in tests |
| **PostgreSQL (Neon)** | A big database in the cloud | The database on the live site |
| **Jinja** | Templates for HTML | Making each page |
| **HTML, CSS, JavaScript** | The languages of web pages | The look, and drag and drop |
| **SVG** | Pictures made from code | The charts and the icons |
| **markdown-it-py + nh3** | Markdown and safe HTML | Task descriptions that can't run scripts |
| **pytest** | A testing tool | Over 240 tests, for example for every role and every move |
| **Playwright** | A browser robot | The screenshots and the app icon |
| **Render** | A hosting platform | Running the live site |
| **GitHub** | Code hosting | Keeping the code and pull requests |

## Run It on Your Computer

You need Python 3.13.

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\flask --app planit upgrade-db
.venv\Scripts\flask --app planit run --debug --port 5007
```

Then open http://127.0.0.1:5007 and sign up, or press **Try demo**.

Run the tests:

```
.venv\Scripts\python -m pytest
```
