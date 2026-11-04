"""Draw the app icon (planit/static/icons/): the ringed planet with a tick, white on a blue tile.

It is the same drawing as the logo in templates/_icons.html, in the icon's own
colours. Phones and browsers want PNG pictures in fixed sizes, plus favicon.ico.
Run this again after changing the design. Like take_screenshots.py, it uses
Playwright + Edge (Playwright isn't in requirements.txt: borrow another
project's, or pip install playwright):

    ..\\expense_tracker\\.venv\\Scripts\\python docs\\make_icons.py
"""
import struct
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parent.parent
ICONS = ROOT / "planit" / "static" / "icons"

# The bright accent, not the navy: a navy tile vanishes on a dark browser tab
# or a dark phone screen, and this blue stands out on light and dark alike.
TILE = "#2f6bff"
PLANET = "#ffffff"
RING = "#bcd3ff"
TICK = "#2f6bff"

# (file, size, shape). "rounded" has see-through corners, for browser tabs and
# installed apps. "square" fills every pixel: iPhones round the corners
# themselves, and Android crops a "maskable" icon into its own shape.
PNGS = [
    ("icon-32.png", 32, "rounded"),
    ("icon-192.png", 192, "rounded"),
    ("icon-512.png", 512, "rounded"),
    ("icon-maskable-512.png", 512, "square"),
    ("apple-touch-icon.png", 180, "square"),
]
ICO_SIZES = (16, 32, 48)


def page_html(size, shape):
    radius = round(size * 0.22) if shape == "rounded" else 0
    # A maskable icon can be cropped to a circle, so its drawing stays in the middle 70%.
    drawing = size * (0.62 if shape == "square" else 0.78)
    # The planet's back half of the ring is drawn first, then the planet, then the
    # front half on top of it, so the ring goes around the planet.
    return f"""<!doctype html>
<style>
  html, body {{ margin: 0; background: transparent; }}
  .tile {{ width: {size}px; height: {size}px; background: {TILE}; border-radius: {radius}px;
           display: flex; align-items: center; justify-content: center; overflow: hidden; }}
</style>
<div class="tile">
  <svg width="{drawing}" height="{drawing}" viewBox="0 0 32 32">
    <ellipse cx="16" cy="16" rx="15" ry="5.2" fill="none" stroke="{RING}" stroke-width="2.2" transform="rotate(-24 16 16)"/>
    <circle cx="16" cy="16" r="10" fill="{PLANET}"/>
    <path d="M2.4 21.6 A15 5.2 -24 0 0 29.6 10.4" fill="none" stroke="{RING}" stroke-width="2.2"/>
    <path d="M11.5 16.3l3.1 3.1 6-6.2" fill="none" stroke="{TICK}" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"/>
  </svg>
</div>"""


def render(browser, size, shape):
    page = browser.new_page(viewport={"width": size, "height": size})
    page.set_content(page_html(size, shape))
    png = page.locator(".tile").screenshot(omit_background=True)
    page.close()
    return png


def write_ico(path, pictures):
    """favicon.ico is a small header, a list, then the PNG files themselves."""
    header = struct.pack("<HHH", 0, 1, len(pictures))
    offset = 6 + 16 * len(pictures)
    entries, data = b"", b""
    for size, png in pictures:
        entries += struct.pack("<BBBBHHII", size, size, 0, 0, 1, 32, len(png), offset + len(data))
        data += png
    path.write_bytes(header + entries + data)


def main():
    ICONS.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge")
        for name, size, shape in PNGS:
            (ICONS / name).write_bytes(render(browser, size, shape))
            print("saved", name)
        write_ico(ICONS / "favicon.ico", [(size, render(browser, size, "rounded")) for size in ICO_SIZES])
        print("saved favicon.ico")
        browser.close()


if __name__ == "__main__":
    main()
