# Plan-It: Project Management Board

## Context
This is a new learning project in `jcatibog014/project_management_board`. The repo has only a README for now. The skills to practise are **roles, relationships, permissions and workflows**. You chose:
- **Name:** Plan-It, "Your projects, in orbit."
- **Look:** Blueprint.
- **Roles:** set per project (Owner, Manager, Member, Viewer).
- **Workflow:** fixed columns with rules.
- **Feature groups:** all four (Collaboration, Planning views, Task details, Insights).
- **Accounts:** open sign-up, plus a temporary demo for each visitor with a "View as" switch.
- **Project kind:** each new project is either **Personal** (just you) or **Team** (people with roles, plus saved Teams that bring a whole group in at once).

## Setup
- Clone the repo to `C:\Users\USER\Documents\Workspace\project_management_board`.
- Branch `build-plan-it`. **One PR, with one commit per stage.** You picked this for Sangkap, Akda and Hire Wire.
- Package `planit`, local port **5007**. Hire Wire uses 5006, and another session is building it right now, so its folder stays untouched.
- **Stack:** the same as Akda. Flask 3.1, SQLAlchemy 2.0 + Alembic, SQLite locally and Neon Postgres live, Render (Singapore), markdown-it-py + nh3 for task descriptions and comments, and pytest.

### Reuse from Akda (`Documents\Workspace\personal_blog`)
- `akda/__init__.py`: `create_app`, the security headers and CSP, the error handlers, ProxyFix.
- `akda/db.py`: `Base`, `session()`, `upgrade_db`, the `upgrade-db` CLI. `akda/migrations/env.py`.
- `akda/auth.py`: `check_login` with its lockout, `log_in`, `safe_next`, `load_user` with `session_version`, `csrf_token` and `check_csrf`, `login_required`.
- The pattern in `akda/permissions.py`: every rule is a plain function, and views and templates never read a role directly. Also `refuse()` from `akda/views/desk.py`, which gives 404 when you can't see something and 403 when you can't change it.
- `tests/conftest.py` (`app`, `client`, `post()`, `make_user()`), `tests/test_permissions.py` (the role × action table), `tests/test_demo.py` (no empty pages), `tests/test_readme.py`, `tests/test_migrations.py`.
- `docs/take_screenshots.py`, `docs/make_practice_data.py`, `docs/make_icons.py`, `static/theme.js`, `render.yaml`, and the layout of `AGENTS.md` and `CLAUDE.md`.

## Roles and permissions (`planit/permissions.py`)
Your role in a project is the **highest** of two things: the role you were given directly, and any role a Team you belong to was given (`effective_role(user, project)`).

| Action | Owner | Manager | Member | Viewer |
|---|---|---|---|---|
| See the board, tasks, activity and dashboard | ✓ | ✓ | ✓ | ✓ |
| Comment | ✓ | ✓ | ✓ | ✓ |
| Create tasks | ✓ | ✓ | ✓ | – |
| Edit or delete any task | ✓ | ✓ | – | – |
| Edit tasks you created or are assigned to | ✓ | ✓ | ✓ | – |
| Assign a task to someone else | ✓ | ✓ | only yourself ("Take it") | – |
| Approve In Review → Done, reopen a Done task | ✓ | ✓ | – | – |
| Manage labels and WIP limits | ✓ | ✓ | – | – |
| Add or remove people, Teams and invite links | ✓ | ✓ (only below Manager) | – | – |
| Rename the project, edit its details | ✓ | ✓ | – | – |
| Archive, delete, transfer ownership, switch Personal ↔ Team | ✓ | – | – | – |

- **Personal projects:** you are the Owner. Other people can't be added, and the Members tab is hidden. "Make it a team project" switches it.
- **Teams:** the Team's creator manages who is in it. You add a Team to a project with one role. Taking someone out of the Team takes away the access the Team gave them.
- **Joining:** a Manager or Owner adds people by username, or makes an invite link with a chosen role. Only a hash of the token is stored, and each link works once (Akda's `invites.claim`).

## Workflow (`planit/workflow.py`)
The columns are Backlog → To Do → In Progress → In Review → Done.
- **Allowed moves:**
  - Backlog ⇄ To Do
  - To Do ⇄ In Progress
  - In Progress ⇄ In Review
  - In Review → Done
  - Done → To Do, which reopens the task
- **Rules:**
  - A task needs an assignee before it can go to In Progress.
  - Members move only the tasks they are assigned to.
  - Only a Manager or the Owner can approve to Done or reopen a task.
  - A move into a full column (its WIP limit is reached) is refused, with a message.
- Every move writes an activity row and sends notifications. `TRANSITIONS` and `can_move()` and `move()` sit in this one module and are tested as a table.

## Data model (Alembic migrations 0001…)
- **People and access:**
  - `users`: username, name, password hash, recovery code hash, is_demo, demo_expires_at, session_version, lockout fields.
  - `teams`, `team_members` (users ↔ teams, many-to-many).
  - `projects`: name, key such as `WEB`, description, kind (personal/team), colour, owner_id, due date, archived_at.
  - `project_members` (user, role) and `project_teams` (team, role), each with a CheckConstraint on the role.
  - `invites`.
- **Tasks:**
  - `tasks`: a number within the project (`WEB-12`), title, description, status, priority, assignee, reporter, due date, position, completed_at.
  - `labels` and `task_labels`, `checklist_items`, `wip_limits` (project, status, limit).
- **Collaboration:** `comments`, `notifications` (user, kind, task, actor, read_at), `activity` (project, task, actor, verb, detail).

## Look: Blueprint
- **Colours:**
  - A deep navy sidebar (`#0F1E3D`).
  - A light page (`#F4F7FB`) with a faint 24px blueprint grid.
  - White cards with 6px corners, and one bright blue accent (`#2F6BFF`).
  - A colour stripe for each status: Backlog slate, To Do sky, In Progress amber, In Review violet, Done green.
- **Dark mode:** a navy-black page with the grid in light blue lines.
- **Fonts and icons:** Space Grotesk for headings and Inter for text, both self-hosted. The logo is a ringed planet, drawn by `docs/make_icons.py`, and the app is installable (manifest + icons).
- **Neat text:** Title Case for the menu and headings, sentence case for buttons, no decorative emoji, controls at equal heights.
- Theme and Log out sit in **Settings** and in the account menu, not in the header.

```
┌────────────┬──────────────────────────────────────────────────┐
│ ◯ Plan-It  │ Website Revamp  [Team]       Board List Dash ... │
│            │──────────────────────────────────────────────────│
│ Home       │ Backlog   To Do 3   In Progress 2/3  Review  Done│
│ My Tasks   │ ┌──────┐ ┌──────┐  ┌──────┐         ┌──────┐     │
│ Calendar   │ │WEB-12│ │WEB-9 │  │WEB-4 │         │WEB-7 │     │
│ Inbox (3)  │ │Title │ │Title │  │Title │         │Title │     │
│ Teams      │ │▪UI ⚑ │ │Due 5d│  │☑2/5 💬│        │  (A) │     │
│ ─ Projects │ └──────┘ └──────┘  └──────┘         └──────┘     │
│ • Website  │ + Add task                                       │
│ • Mobile   │                                                  │
│ (A) Ana ▾  │                                                  │
└────────────┴──────────────────────────────────────────────────┘
```
On phones, a ☰ button opens the menu, and the board scrolls sideways one column at a time.

## Pages
- **Sign-up, Log in, Demo:** a split-screen login. A recovery code is shown once at sign-up, because there is no email.
- **Home:** a greeting; what you have overdue, due today and due this week; your projects with progress bars; recent activity.
- **Projects:** cards with a Personal or Team badge, a progress bar and member avatars. **New project** asks for name, key, Personal/Team, and (for Team) Teams and people to add.
- **Project tabs:**
  - Board (drag and drop, with a "Move to" menu that works without JavaScript)
  - List (filter by assignee, label, priority and due date)
  - Calendar
  - Dashboard
  - Activity
  - Members (team projects only)
  - Project Settings (labels, WIP limits, invite links, archive)
- **Task page:**
  - Title and description.
  - A side panel with the status (showing only the moves you're allowed), assignee, due date, priority and labels.
  - A checklist, comments with @mentions, and the task's activity.
- **My Tasks:** everything assigned to you across all projects, grouped as Overdue, Today, This Week, Later and No Date.
- **Calendar:** a month grid of all your deadlines.
- **Inbox:** notifications for being @mentioned, assigned, asked to review, approved, sent back, or added to a project. "Mark all read."
- **Teams:** a list of Teams, and a Team page showing its people and the projects it has access to.
- **Settings:** Appearance, Name, Password, a new recovery code. For the demo, the View As choice.
- **Dashboard (Insights):** progress, tasks in each status, each person's open tasks (workload), tasks finished per week for the last 8 weeks, and the overdue count. The charts are server-made SVG with no chart library, which keeps pages small on a slow network.

## Demo
- **The sandbox:** `POST /demo` makes a fresh `demo-xxxx` user that expires after 24 hours. Expired demos are cleared each time a new one starts, and there is a `purge-demos` CLI.
- **Sample data:** the company "Orbit Labs" with sample teammates who can't log in (Ana, Ben, Cara, Dev, Eli), a Design Team and a Dev Team, and these projects:
  - Website Revamp: a team project where the demo user is Owner.
  - Mobile App Launch: the demo user is a Member through the Dev Team.
  - Marketing Plan: the demo user is a Viewer.
  - Learn Flask: a personal project.
- **What the sample data shows:** tasks in every column, overdue and due-soon tasks, checklists, labels, comments with mentions, unread notifications, a full WIP column, and 8 weeks of finished tasks so the charts have data.
- **View As:** a small "Viewing as: Owner ▾" pill at the bottom of the sidebar (demo only, also in Settings). It sets a session value that `effective_role` uses for the demo's team projects, so the buttons, columns and pages change straight away.
- **Test:** `tests/test_demo.py` fails if any page the demo can open is empty.

## Stages (one commit each, in one PR)
1. **Setup:** clone, the skeleton from Akda, auth (sign-up, log in, recovery code, lockout, CSRF), the Blueprint layout, Settings and the theme, `AGENTS.md`, `CLAUDE.md`, `docs/PLAN.md`, `render.yaml`.
2. **Projects and access:** projects (Personal/Team), members, Teams, invite links, `permissions.py` with its table test.
3. **Board and workflow:** creating and editing tasks, the board, `workflow.py`, WIP limits, the task page, the activity log.
4. **Task details:** labels, priority, checklists, drag and drop.
5. **Collaboration:** comments, @mentions, the Inbox.
6. **Planning views:** Home, My Tasks, Calendar, List with filters, due badges.
7. **Insights:** the project Dashboard.
8. **Demo and polish:** sample data for every page (it grows with each stage, and this stage finishes it), View As, `test_demo`, icons and installing, README screenshots for every feature (plain English, with a table of the tools used), and `test_readme`.

## Verification
- `pytest` runs green on SQLite. Every stage adds tests, and the main ones are the permission table, the workflow table, Team-based access (gained and lost), and that demos stay separate from each other.
- `flask --app planit run --port 5007`. Then sign up, make a Personal and a Team project, add a Team, use an invite link in a second browser, move tasks through every column as each role, and check that refused moves give 403 and a message.
- Try the demo with each View As role and check that every page has content.
- Screenshots are taken with `docs/take_screenshots.py`, using Playwright from expense_tracker's `.venv`. Check them for alignment before opening the PR. PR image links use raw.githubusercontent.com addresses.
- After the PR: save a memory note for Plan-It. Going live (Neon + the Render Blueprint `plan-it`) is left for you to do, with step-by-step guidance.
