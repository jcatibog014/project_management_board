# AGENTS.md

This file guides AI coding agents (Claude Code, Codex, Cursor, Copilot and others) working in this repository.

## Overview

**Plan-It** ("Your projects, in orbit."), a project management board in Python (Flask). The repo is `project_management_board` and the Python package is `planit`. People make projects, share them with people or whole Teams, and move tasks through a fixed workflow. The plan is `docs/PLAN.md`.

It is a learning project for **roles, relationships, permissions and workflows**, so those parts stay easy to read: short comments that explain *why*, login written by hand (no Flask-Login), and no extra libraries unless the owner asks for them. Write the README in simple (A1-level) English.

Python 3.13 is at `%LOCALAPPDATA%\Programs\Python\Python313\python.exe`. Use the virtual environment:

- Install: `.venv\Scripts\python -m pip install -r requirements.txt` (create `.venv` with `python -m venv .venv` first if it's missing).
- First time: `.venv\Scripts\flask --app planit upgrade-db` (makes the tables). Then sign up on the site.
- Run: `.venv\Scripts\flask --app planit run --debug --port 5007`, then open http://127.0.0.1:5007. (Ports: Swap Meter 5000, Ambon Alert 5001, Ang Gastos! 5002, Sangkap 5003, Gawi 5004, Akda 5005, Hire Wire 5006.)
- Test: `.venv\Scripts\python -m pytest`. Every test gets a fresh SQLite file and never uses the internet. Set `TEST_DATABASE_URL` to an **empty** Neon branch to run the same tests on PostgreSQL (each test drops and remakes the tables). SQLAlchemy warnings fail the tests (`pytest.ini`).
- Other commands: `set-password <name>`, `purge-demos` (starting a demo does it too).
- Screenshots: `docs/take_screenshots.py` (Playwright + Edge, borrowed from another project's `.venv`; its top comment has the steps). Every picture comes from Try Demo. App icon: `docs/make_icons.py` (the logo's ringed planet, white on the blue accent, into `planit/static/icons/`).

## Architecture

- **`planit/permissions.py` holds EVERY rule about roles**, as plain functions of an `Access` (user, project, role). Views and templates (`can.can_edit_task(access, task)`) ask these and never compare roles themselves. `tests/test_permissions.py` is a table of every role against every action. **Add new rules there, with a table row.**
  - **Roles are per project:** Owner (`projects.owner_id`, exactly one), Manager, Member, Viewer (`project_members` for one person, `project_teams` for a whole Team). `effective_role()` takes the **highest** and caches it per request. A Manager only gives roles below their own and can't touch another Manager.
  - **Personal projects** have only the owner: no Members tab, nothing to share. A Team project can become Personal again only when nobody else is in it.
  - **Archived = read-only for everyone** (`Access.writable`); only the owner can bring it back.
  - **404 or 403:** a project you can't open is 404, so its name never leaks; an action you may not do in a project you can see is 403 (`views/projects.py: load()` and `require()`).
  - **Every list starts from `projects.visible_filter(user)`** (projects, Home, My Tasks, Calendar), so tasks from other projects never show.
- **`planit/workflow.py` holds the workflow:** `TRANSITIONS` (one step forward or back; Done only reopens to To Do), `move_problem()` (the pure rules, a table in `tests/test_workflow.py`), `limit_problem()` (Work in Progress limits) and `move()`, which writes the history and the notifications. The board's drag and drop (fetch with `Accept: application/json`) and the Move buttons both call `move()`.
- **History:** `activity.py` writes one `Activity` row per change; `_activity.html` turns it into a sentence. A deleted task keeps its lines (`note` has its key and title).
- **Inbox:** `notify.send()` (never to the actor, never to someone who can't open the project). Mentions: `comments.py` (`@username`; demo teammates use their short name). Comments are plain text, escaped, with known mentions marked by `with_mentions()`.
- **Task numbers:** `tasks.create()` raises `next_number` with an UPDATE in the database, so two people adding a task at once get different numbers.
- **Demo:** Try Demo makes a fresh `demo-<tag>-sam` ("Sam Rivera") with five sample teammates (`demo-<tag>-ana` ...) and the Orbit Labs company from `seed.py`. All expire after 24 hours and are deleted (with everything they own) when the next demo starts. Demo users can't log in with the form, real people never find them by username, and a demo only finds its own teammates (`projects.find_user`). **View As** (sidebar and Settings) plays Manager, Member or Viewer in the demo's team projects (`g.view_as`), but owning stays real. **Every page the demo can open must show an example, so add sample data in `seed.py` with every new feature** (`tests/test_demo.py` checks each page).
- **Charts:** the Dashboard is SVG drawn by the server (`insights.py`, `project/dashboard.html`): no chart library. Every bar has its number, a `<title>` for hover, and a table view. The status colours were checked with the dataviz validator in light and dark; re-run it if you change them.

- **Login:** `auth.py`. Hashes from Werkzeug, 5 wrong passwords (or recovery codes) = 15-minute lock, `load_user()` checks `session_version` on every request (adding 1 to it ends every session: password change). CSRF: every POST needs `csrf_token` (`{{ csrf() }}` from `_macros.html`; JS sends it as the `X-CSRF-Token` header; tests use `post()` from `conftest.py`). There is no email: sign-up shows a **recovery code** once (`/recovery-code`), stored as a hash; `/forgot` uses it to set a new password and then gives a new code.
- **Database:** SQLAlchemy 2.0 ORM (typed `Mapped[...]`), plain (not Flask-SQLAlchemy). `planit/db.py` makes one engine per app and one session per request: `db.session()`. Nothing is saved without `.commit()`. `expire_on_commit=False`. SQLite locally (`instance/planit.sqlite`, git-ignored; foreign keys on per connection), PostgreSQL (Neon, psycopg 3) when `DATABASE_URL` is set. Keep code portable: no dialect-only SQL. Times are naive UTC (`dates.utcnow()`); people see Philippine time (`dates.to_local()`, the filters in `formatting.py`). Deadlines are plain dates compared with `dates.today()`.
- **Migrations: Alembic**, in `planit/migrations/`. `flask --app planit upgrade-db` runs them; Render runs it before gunicorn.
  - **To change the schema:** edit `models.py`, then `.venv\Scripts\alembic revision --autogenerate -m "what changed" --rev-id 000N`, **read the new file and fix it**, and commit it. Never edit a migration that has run on the live site. `tests/test_migrations.py` fails if the models and the migrations disagree.
- **Every page works without JavaScript.** `app.js` only adds extras. Use `.no-js-only` for fallbacks. The CSP (`__init__.py`) has no inline scripts or styles, so **never use `style=""` or inline `<script>`**: sizes and colours are classes, and charts are SVG attributes.

## UI rules (the owner's priority is neatness)

- **Look: Blueprint.** A deep navy sidebar, a light page with a faint 24px grid, white cards, one bright blue accent (`--accent`). Every task status has its own colour (`--backlog`, `--todo`, `--in_progress`, `--review`, `--done`; set `--s` with a `.status-*` class). Space Grotesk for headings, Inter for text, self-hosted in `static/fonts/`. Dark mode is defined twice in `style.css` (device setting + the choice in Settings); change both blocks together.
- **Settings holds the controls, and the menus only navigate.** The theme (Device, Light or Dark, saved per device in `localStorage`; `theme.js` applies it before the page draws) is only on `/settings`. Log out is there too, and in the account menu at the bottom of the sidebar.
- **No decorative emoji.** Icons are the line SVGs in `_icons.html`.
- **Title Case** for the menu, page titles (`h1`), section headings, tabs, empty-state titles and anything that names a page ("My Tasks", "In Review"). Small words (a, an, the, and, or, of, in, on, to, for, with, as, at, by) stay lowercase unless first. **Sentence case** for everything else: action buttons ("New project", "Save task"), labels, hints, messages. The main button of a page is last on the right.
- Controls are the same height (`--control-height`) with bottoms aligned. Sizes in `rem`; the root font steps up at 1600 / 1920 / 2300px.
- The sidebar shows from 56rem up; below that a ☰ button opens it.
- **Every PR must keep the README's pictures up to date (the owner's standing rule).** Screenshots live in `docs/screenshots/` and every one is shown in the README. If a PR visibly changes a page, retake its pictures; if it adds a page or feature, add a line to `PAGES` in `docs/take_screenshots.py` and a picture to the README. `tests/test_readme.py` fails if they disagree. In a PR description, link pictures with a full `raw.githubusercontent.com` address.
- Commit messages and PR bodies go through files (`git commit -F`, `gh pr create --body-file`): PowerShell 5.1 breaks quotes in arguments.
