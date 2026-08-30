"""Browser tests for the tooltip layer.

The unit tests in ``test_smoke.py`` prove the right text reaches the HTML. What
they cannot check is the part that made us position the bubble from JS in the
first place: that it actually becomes visible, is not clipped by the scrolling
table around the list action buttons, flips when there is no room above, stays
inside a narrow viewport, and is readable in dark mode.

Playwright and a browser binary are optional; without them the whole module is
skipped, so `pytest -q` stays green on a plain checkout and in CI. To run them:

    pip install playwright && playwright install chromium
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import socket
import subprocess
import sys
import tempfile
import time

import pytest

try:
    from playwright.sync_api import sync_playwright
except ImportError as exc:  # not installed, or installed but broken
    pytest.skip(f"playwright unavailable: {exc}", allow_module_level=True)

REPO = pathlib.Path(__file__).resolve().parent.parent
ADMIN_USER = "admin"
ADMIN_PASS = "e2epass12345"

# The bubble's background comes from --bg-elev, which the theme swaps.
LIGHT_BG = "rgb(255, 255, 255)"
DARK_BG = "rgb(28, 28, 30)"


def _catalog(lang: str) -> dict:
    path = REPO / "app" / "i18n" / f"{lang}.json"
    return json.loads(path.read_text(encoding="utf-8"))


DE = _catalog("de")
EN = _catalog("en")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def browser():
    """A chromium instance, or skip the module if no binary is installed."""
    with sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:  # noqa: BLE001 - any launch failure means "not available"
            pytest.skip(f"no chromium binary: {exc}")
        yield b
        b.close()


@pytest.fixture(scope="module")
def server():
    """Serve the real app on a free port against a throwaway database."""
    tmp = tempfile.mkdtemp(prefix="stp_e2e_")
    port = _free_port()
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{tmp}/e2e.db",
        "UPLOAD_DIR": f"{tmp}/uploads",
        "BACKUP_DIR": f"{tmp}/backups",
        "SECRET_KEY": "e2e-secret-key",
        "BOOTSTRAP_ADMIN_USERNAME": ADMIN_USER,
        "BOOTSTRAP_ADMIN_PASSWORD": ADMIN_PASS,
    }
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=str(REPO),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        if proc.poll() is not None:
            out = proc.stdout.read().decode("utf-8", "replace") if proc.stdout else ""
            pytest.fail(f"uvicorn exited early:\n{out}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.1)
    else:
        proc.kill()
        pytest.fail("uvicorn did not start in time")

    yield base

    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture(scope="module")
def page(browser, server):
    """A logged-in page with one object present, so the lists are not empty."""
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    pg = ctx.new_page()

    pg.goto(f"{server}/login")
    pg.fill('input[name="username"]', ADMIN_USER)
    pg.fill('input[name="password"]', ADMIN_PASS)
    pg.click('button[type="submit"]')
    pg.wait_for_selector("nav.nav")

    pg.goto(f"{server}/assets/new")
    pg.fill("#uid", "E2E-1")
    pg.fill("#name", "Tooltip Test Shaft")
    pg.click('button[type="submit"]')
    pg.wait_for_url(re.compile(r"/assets$"))

    yield pg
    ctx.close()


def bubble(page):
    return page.locator(".tooltip")


def is_shown(page) -> bool:
    return "visible" in (bubble(page).get_attribute("class") or "")


def opacity(page) -> float:
    return float(bubble(page).evaluate("el => getComputedStyle(el).opacity"))


def wait_shown(page, shown=True, timeout=2000):
    """Wait past the 0.12s fade, so callers never sample a mid-transition value."""
    target = 1.0 if shown else 0.0
    deadline = time.time() + timeout / 1000
    while time.time() < deadline:
        if is_shown(page) is shown and abs(opacity(page) - target) < 0.01:
            return
        page.wait_for_timeout(25)
    raise AssertionError(
        f"tooltip visible={is_shown(page)} opacity={opacity(page)}, expected shown={shown}"
    )


# ------------------------------------------------------------------ the tests


def test_hovering_a_field_marker_shows_its_text(page, server):
    page.goto(f"{server}/entries/new")
    assert not is_shown(page), "the bubble must start hidden"

    page.hover('label[for="operating_hours"] .tip')
    wait_shown(page)
    assert bubble(page).inner_text() == DE["tip.entry.operating_hours"]
    assert opacity(page) == 1.0

    page.mouse.move(0, 0)
    wait_shown(page, shown=False)


def test_keyboard_focus_shows_and_escape_hides(page, server):
    """A native title= never does this; it is the reason for the custom layer."""
    page.goto(f"{server}/entries/new")
    marker = page.locator('label[for="asset_id"] .tip')
    marker.focus()
    wait_shown(page)
    assert bubble(page).inner_text() == DE["tip.entry.asset"]

    page.keyboard.press("Escape")
    wait_shown(page, shown=False)


def test_action_button_tooltip_is_not_clipped_by_the_scrolling_table(page, server):
    """The bubble must escape .table-wrap (overflow-x: auto), which clips ::after."""
    page.goto(f"{server}/assets")
    wrap = page.locator(".table-wrap")
    delete_btn = page.locator(".table-wrap button[data-tip]").first

    delete_btn.hover()
    wait_shown(page)
    assert bubble(page).inner_text() == DE["tip.action.delete"]

    # It lives on <body>, not inside the scroll container that would clip it.
    assert bubble(page).evaluate("el => el.parentElement.tagName") == "BODY"

    box = bubble(page).bounding_box()
    wrap_box = wrap.bounding_box()
    assert box["height"] > 10 and box["width"] > 40, f"bubble collapsed: {box}"

    # Fully on screen, and not confined to the table's own rectangle.
    vw = page.evaluate("() => document.documentElement.clientWidth")
    vh = page.evaluate("() => window.innerHeight")
    assert box["x"] >= 0 and box["x"] + box["width"] <= vw, (box, vw)
    assert box["y"] >= 0 and box["y"] + box["height"] <= vh, (box, vh)
    assert box["y"] < wrap_box["y"] + wrap_box["height"], "bubble should sit near its trigger"


def test_tooltip_flips_below_a_trigger_at_the_top_edge(page, server):
    """Nav icons sit ~15px from the top; there is no room for a bubble above."""
    page.goto(f"{server}/entries")
    icon = page.locator(".nav-right a[data-tip]").last  # sign out
    icon.hover()
    wait_shown(page)

    icon_box = icon.bounding_box()
    box = bubble(page).bounding_box()
    assert box["y"] >= icon_box["y"] + icon_box["height"], (
        f"expected the bubble below the icon: bubble={box}, icon={icon_box}"
    )
    assert box["y"] >= 0


def test_tooltip_text_follows_the_language_switch(page, server):
    page.goto(f"{server}/entries/new")
    page.hover('label[for="operating_hours"] .tip')
    wait_shown(page)
    assert bubble(page).inner_text() == DE["tip.entry.operating_hours"]

    page.click('.lang-switch a[href="/lang/en"]')
    page.wait_for_load_state()
    page.goto(f"{server}/entries/new")
    page.hover('label[for="operating_hours"] .tip')
    wait_shown(page)
    text = bubble(page).inner_text()
    assert text == EN["tip.entry.operating_hours"]
    assert text != DE["tip.entry.operating_hours"]

    page.click('.lang-switch a[href="/lang/de"]')
    page.wait_for_load_state()


def test_tooltip_stays_inside_a_narrow_viewport(page, server):
    """A right-edge trigger at phone width must not push the bubble off screen."""
    page.set_viewport_size({"width": 380, "height": 720})
    try:
        page.goto(f"{server}/entries")
        # The sign-out icon sits hard against the right edge - centring a 260px
        # bubble on it would run off screen unless it is clamped.
        icon = page.locator(".nav-right a[data-tip]").last
        icon.hover()
        wait_shown(page)

        box = bubble(page).bounding_box()
        icon_box = icon.bounding_box()
        vw = page.evaluate("() => document.documentElement.clientWidth")

        centred_right = icon_box["x"] + icon_box["width"] / 2 + box["width"] / 2
        assert centred_right > vw, (
            f"trigger is not near enough to the edge to test clamping "
            f"(centred right edge {centred_right} <= viewport {vw})"
        )

        assert box["x"] >= 0, box
        assert box["x"] + box["width"] <= vw, (box, vw)
        assert not page.evaluate(
            "() => document.documentElement.scrollWidth > document.documentElement.clientWidth"
        ), "the bubble must not make the page scroll sideways"
    finally:
        page.set_viewport_size({"width": 1280, "height": 900})


@pytest.mark.parametrize("theme,expected_bg", [("light", LIGHT_BG), ("dark", DARK_BG)])
def test_tooltip_is_readable_in_both_themes(page, server, theme, expected_bg):
    page.goto(f"{server}/entries/new")
    page.evaluate("t => localStorage.setItem('stp-theme', t)", theme)
    page.reload()
    assert page.evaluate("() => document.documentElement.dataset.theme") == theme

    page.hover('label[for="description"] .tip')
    wait_shown(page)

    styles = bubble(page).evaluate(
        "el => { const s = getComputedStyle(el);return {bg: s.backgroundColor, fg: s.color}; }"
    )
    assert styles["bg"] == expected_bg, styles

    def luminance(rgb: str) -> float:
        r, g, b = (int(v) for v in re.findall(r"\d+", rgb)[:3])
        return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255

    contrast = abs(luminance(styles["bg"]) - luminance(styles["fg"]))
    assert contrast > 0.5, f"tooltip text is hard to read in {theme}: {styles}"
