"""Very small JSON-file based i18n helper (German / English)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.config import settings

I18N_DIR = Path(__file__).resolve().parent.parent / "i18n"
LANGUAGE_COOKIE = "lang"


@lru_cache
def _load(lang: str) -> dict[str, str]:
    path = I18N_DIR / f"{lang}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_lang(lang: str | None) -> str:
    if lang and lang in settings.supported_languages:
        return lang
    return settings.default_language


class Translator:
    """Callable translator bound to a language, used as ``t`` in templates."""

    def __init__(self, lang: str):
        self.lang = normalize_lang(lang)
        self._table = _load(self.lang)
        self._fallback = _load(settings.default_language)

    def __call__(self, key: str, **kwargs) -> str:
        text = self._table.get(key) or self._fallback.get(key) or key
        if kwargs:
            try:
                return text.format(**kwargs)
            except (KeyError, IndexError):
                return text
        return text


def get_translator(lang: str | None) -> Translator:
    return Translator(lang)
