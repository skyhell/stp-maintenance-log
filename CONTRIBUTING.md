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

## Project layout

```
app/
  main.py         FastAPI app, middleware, startup
  config.py       Settings from .env
  database.py     SQLAlchemy engine/session
  models/         ORM models
  routers/        HTTP routes (auth, entries, assets, map, admin, account)
  services/       security, storage, i18n, activities, twofa, pdf_export, backup
  templates/      Jinja2 templates (+ HTMX/Alpine)
  static/         CSS, JS, vendored libs (htmx, alpine, leaflet)
  i18n/           de.json, en.json
deploy/           install.sh, systemd unit, nginx example
tests/            pytest smoke/integration tests
```

## Guidelines

- Keep the code style consistent with what is already there (type hints,
  `from __future__ import annotations`, small focused functions).
- Add or update a translation key in **both** `app/i18n/de.json` and
  `app/i18n/en.json` whenever you add user-facing text.
- Add a test for new routes or services where practical.
- Never commit secrets. `.env` and `data/` are gitignored.
- All POST forms must include the CSRF token and be verified server-side.

## Adding a new language

1. Copy `app/i18n/en.json` to `app/i18n/<code>.json` and translate the values.
2. Add the code to `supported_languages` in `app/config.py`.

## Commit messages

Short, imperative summary lines (e.g. "Add PDF export for date range").
Reference issues where relevant.
