"""Take the README screenshots (docs/screenshots/*.png).

Retake them in every pull request that visibly changes a page, and add a new
one when a page or feature is added: the README shows everything Plan-It can
do. tests/test_readme.py fails if the pictures and the README disagree.

Every picture comes from "Try demo", so only the made-up Orbit Labs people
show. Use an empty practice database, never the live one. It uses Microsoft
Edge, which Windows already has, through Playwright. Playwright is only a tool
for this script, so it is not in requirements.txt (borrow another project's):

    $env:DATABASE_URL = "sqlite:///C:/Temp/planit-screenshots.sqlite"
    .venv\\Scripts\\flask --app planit upgrade-db
    .venv\\Scripts\\flask --app planit run --port 5007        (keep this one running)
    ..\\expense_tracker\\.venv\\Scripts\\python docs\\take_screenshots.py

Every picture is one screen (no full-page shots), so they are all the same
size and the README table stays even. Add a line to PAGES when a page is added.
"""
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:5007"
OUT = Path(__file__).parent / "screenshots"
DESKTOP = {"width": 1440, "height": 900}
PHONE = {"width": 390, "height": 844}

# (file name, address, theme, screen size, View As role or None).
# {web}, {app}, {mkt} and {lf} are the demo's four projects.
PAGES = [
    ("login.png", "/login", "light", DESKTOP, None),
    ("home.png", "/", "light", DESKTOP, None),
    ("board.png", "{web}", "light", DESKTOP, None),
    ("board-dark.png", "{web}", "dark", DESKTOP, None),
    ("task.png", "{web}/tasks/5", "light", DESKTOP, None),
    ("comments.png", "{web}/tasks/5#comments", "light", DESKTOP, None),
    ("list.png", "{app}/list?status=open", "light", DESKTOP, None),
    ("dashboard.png", "{web}/dashboard", "light", DESKTOP, None),
    ("dashboard-dark.png", "{app}/dashboard", "dark", DESKTOP, None),
    ("members.png", "{web}/members", "light", DESKTOP, None),
    ("project-settings.png", "{web}/settings", "light", DESKTOP, None),
    ("my-tasks.png", "/my-tasks", "light", DESKTOP, None),
    ("calendar.png", "/calendar", "light", DESKTOP, None),
    ("calendar-week.png", "/calendar?week=", "light", DESKTOP, None),
    ("search.png", "/search?q=logo", "light", DESKTOP, None),
    ("inbox.png", "/inbox", "light", DESKTOP, None),
    ("activity.png", "{web}/activity", "light", DESKTOP, None),
    ("teams.png", "/teams", "light", DESKTOP, None),
    ("new-project.png", "/projects/new?kind=team", "light", DESKTOP, None),
    ("projects.png", "/projects", "light", DESKTOP, None),
    ("view-as-viewer.png", "{web}/tasks/8", "light", DESKTOP, "viewer"),
    ("member-board.png", "{app}", "light", DESKTOP, None),
    ("settings.png", "/settings", "light", DESKTOP, None),
    ("phone.png", "{web}", "light", PHONE, None),
]

PROJECTS = {"web": "Website Revamp", "app": "Mobile App Launch", "mkt": "Marketing Plan", "lf": "Learn Flask"}


def start_demo(browser, theme, size):
    page = browser.new_page(viewport=size, color_scheme=theme)
    page.goto(f"{BASE}/login")
    page.get_by_role("button", name="Try demo").click()
    page.wait_for_url(f"{BASE}/")
    return page


def project_urls(page):
    """{web: "/projects/1", ...} from the sidebar's project links."""
    urls = {}
    for key, name in PROJECTS.items():
        urls[key] = page.locator(".side-links a", has_text=name).first.get_attribute("href")
    return urls


def view_as(page, role):
    page.goto(f"{BASE}/settings")
    page.select_option("#view-as-settings", role)
    page.wait_for_load_state("networkidle")


def save(page, name):
    page.wait_for_load_state("networkidle")  # fonts are in
    page.screenshot(path=str(OUT / name))
    print("saved", name)


def main():
    OUT.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge")
        for name, address, theme, size, role in PAGES:
            if address == "/login":
                page = browser.new_page(viewport=size, color_scheme=theme)
            else:
                page = start_demo(browser, theme, size)
                if role:
                    view_as(page, role)
                address = address.format(**project_urls(page))
            page.goto(BASE + address)
            if "#" in address:
                page.locator("#" + address.split("#")[1]).scroll_into_view_if_needed()
            save(page, name)
            page.close()
        browser.close()


if __name__ == "__main__":
    main()
