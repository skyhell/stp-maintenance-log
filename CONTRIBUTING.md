# Contributing

Thanks for your interest in improving the Sewage Treatment Plant Maintenance Log!

## Development setup

```bash
git clone https://github.com/skyhell/stp-maintenance-log.git
cd stp-maintenance-log
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env           # then edit SECRET_KEY etc.
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000 and log in with the bootstrap admin
(`admin` / `changeme` by default — change it immediately).

## Running tests

```bash
pytest -q
```

Tests use an isolated temporary SQLite database and do not touch your `data/`.

### Browser tests (optional)

`tests/test_tooltips_e2e.py` drives a real Chromium through Playwright to check
what the HTML alone cannot show: that a tooltip actually becomes visible, is not
clipped by the scrolling tables, flips below a trigger at the top edge, stays
inside a narrow viewport, and is readable in both themes. It starts its own
uvicorn on a free port against a throwaway database.

Playwright is not in `requirements.txt`; without it the module skips itself, so
a plain `pytest -q` stays green. To run it:

```bash
pip install playwright
playwright install chromium
pytest tests/test_tooltips_e2e.py
```

## Project layout

```
app/
  main.py         FastAPI app, middleware, startup
  config.py       Settings from .env
  database.py     SQLAlchemy engine/session
  models/         ORM models
  routers/        HTTP routes (auth, entries, assets, map, admin, account)
  services/       security, storage, i18n, activities, twofa, backup, report
  templates/      Jinja2 templates (+ HTMX/Alpine)
  static/         CSS, JS, favicons, vendored libs (htmx, alpine, leaflet)
  i18n/           de.json, en.json
deploy/           install.sh, systemd unit, nginx example
tools/            one-off helpers (make_favicon.py)
tests/            pytest smoke/integration tests
```

## Guidelines

- Keep the code style consistent with what is already there (type hints,
  `from __future__ import annotations`, small focused functions).
- Add or update a translation key in **both** `app/i18n/de.json` and
  `app/i18n/en.json` whenever you add user-facing text. The two catalogs must
  stay key-identical; `pytest` fails if they drift apart.
- Add a test for new routes or services where practical.
- Never commit secrets. `.env` and `data/` are gitignored.
- All POST forms must include the CSRF token and be verified server-side.

## Adding a tooltip

Tooltip texts live in the `tip.*` namespace of the two catalogs and are
rendered server-side, so they follow the selected language automatically.

- **A form field** gets a small "i" marker next to its label:

  ```jinja
  {% import "macros.html" as m %}
  <label for="uid">{{ t('asset.uid') }}{{ m.tip('tip.asset.uid', t) }}</label>
  ```

  Put the marker *inside* the `<label>` - `.field label` is `display: block`,
  so a sibling would drop onto its own line.

- **A button, link or icon** carries the attribute directly:

  ```jinja
  <button class="btn" type="submit" data-tip="{{ t('tip.action.save') }}">...</button>
  ```

Never put `data-tip` and a native `title` on the same element; the browser
would show its own bubble on top of ours, and a test guards against it. Where a
field already has an inline `.hint` below it, skip the tooltip rather than
repeat the text.

`app/static/js/app.js` positions one shared bubble against the viewport - a CSS
`::after` on the trigger would be clipped by the `.table-wrap` and `.nav-links`
scroll containers.

Because `app/services/i18n.py` caches the catalogs with `lru_cache`, **restart
the server** after editing a JSON file.

## Adding a new language

1. Copy `app/i18n/en.json` to `app/i18n/<code>.json` and translate the values.
2. Add the code to `supported_languages` in `app/config.py`.

## Commit messages

Short, imperative summary lines (e.g. "Add CSV export for date range").
Reference issues where relevant.
