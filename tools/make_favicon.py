"""Rasterise app/static/favicon.svg into favicon.ico and apple-touch-icon.png.

Run once after editing the SVG and commit the results - nothing is generated at
runtime:

    python tools/make_favicon.py

Needs Playwright (see CONTRIBUTING.md, browser tests) to render the SVG and
Pillow (pulled in by qrcode[pil]) to write the raster files.
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

STATIC_DIR = Path(__file__).resolve().parent.parent / "app" / "static"
SVG_PATH = STATIC_DIR / "favicon.svg"

ICO_SIZES = (16, 32, 48)
APPLE_TOUCH_SIZE = 180
# iOS applies its own rounded mask, so the touch icon must be an opaque square.
BRAND_BLUE = (0, 113, 227)


def render(page, svg: str, size: int) -> Image.Image:
    """Render the SVG at size x size pixels on a transparent background."""
    page.set_viewport_size({"width": size, "height": size})
    page.set_content(
        f"<style>html,body{{margin:0;background:transparent}}"
        f"svg{{display:block;width:{size}px;height:{size}px}}</style>{svg}"
    )
    png = page.screenshot(omit_background=True)
    return Image.open(io.BytesIO(png)).convert("RGBA")


def main() -> None:
    svg = SVG_PATH.read_text(encoding="utf-8")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        frames = {size: render(page, svg, size) for size in (*ICO_SIZES, APPLE_TOUCH_SIZE)}
        browser.close()

    apple = STATIC_DIR / "apple-touch-icon.png"
    square = Image.new("RGB", (APPLE_TOUCH_SIZE, APPLE_TOUCH_SIZE), BRAND_BLUE)
    square.paste(frames[APPLE_TOUCH_SIZE], mask=frames[APPLE_TOUCH_SIZE])
    square.save(apple, format="PNG")
    print(f"wrote {apple} ({APPLE_TOUCH_SIZE}x{APPLE_TOUCH_SIZE})")

    ico = STATIC_DIR / "favicon.ico"
    largest = frames[max(ICO_SIZES)]
    largest.save(ico, format="ICO", sizes=[(s, s) for s in ICO_SIZES])
    print(f"wrote {ico} ({'/'.join(str(s) for s in ICO_SIZES)})")


if __name__ == "__main__":
    main()
