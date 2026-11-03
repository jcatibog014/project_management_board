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
- Other commands: `set-password <name>`.

## Architecture

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
- Commit messages and PR bodies go through files (`git commit -F`, `gh pr create --body-file`): PowerShell 5.1 breaks quotes in arguments.
