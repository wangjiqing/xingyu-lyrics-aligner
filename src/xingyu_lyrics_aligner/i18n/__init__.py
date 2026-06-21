"""Small JSON-backed i18n helper for CLI-facing text."""

from __future__ import annotations

import json
import os
from importlib import resources
from typing import Any

from xingyu_lyrics_aligner.user_config import load_user_config

DEFAULT_LOCALE = "en-US"
SUPPORTED_LOCALES = ("en-US", "zh-CN")
ENV_LOCALE = "XINGYU_ALIGN_LOCALE"

_active_locale = DEFAULT_LOCALE
_catalog_cache: dict[str, dict[str, str]] = {}


def normalize_locale(locale: str | None) -> str:
    """Return a supported locale, falling back to the default."""
    if not locale:
        return DEFAULT_LOCALE
    normalized = locale.strip()
    return normalized if normalized in SUPPORTED_LOCALES else DEFAULT_LOCALE


def configure_locale(locale: str | None = None) -> str:
    """Set active locale from explicit value, environment, saved config, or default."""
    global _active_locale
    configured = load_user_config().locale
    _active_locale = normalize_locale(locale or os.environ.get(ENV_LOCALE) or configured)
    return _active_locale


def get_locale() -> str:
    """Return the currently active locale."""
    return _active_locale


def available_locales() -> tuple[str, ...]:
    """Return supported locale identifiers."""
    return SUPPORTED_LOCALES


def _load_catalog(locale: str) -> dict[str, str]:
    normalized = normalize_locale(locale)
    if normalized not in _catalog_cache:
        resource = resources.files(__package__).joinpath(f"{normalized}.json")
        with resource.open("r", encoding="utf-8") as file:
            data = json.load(file)
        _catalog_cache[normalized] = {str(key): str(value) for key, value in data.items()}
    return _catalog_cache[normalized]


def translate(key: str, **kwargs: Any) -> str:
    """Translate a CLI text key using the active locale."""
    catalog = _load_catalog(_active_locale)
    fallback = _load_catalog(DEFAULT_LOCALE)
    template = catalog.get(key, fallback.get(key, key))
    return template.format(**kwargs)


configure_locale()
