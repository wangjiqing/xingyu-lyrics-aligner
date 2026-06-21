"""User-level preferences for CLI behavior."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

APP_DIR_NAME = "xingyu-lyrics-aligner"
CONFIG_FILE_NAME = "config.json"


@dataclass(frozen=True)
class UserConfig:
    """Persisted user preferences."""

    locale: str | None = None


def user_config_dir() -> Path:
    """Return the XDG-style user config directory."""
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base) / APP_DIR_NAME
    return Path.home() / ".config" / APP_DIR_NAME


def user_config_path() -> Path:
    """Return the user config file path."""
    return user_config_dir() / CONFIG_FILE_NAME


def load_user_config() -> UserConfig:
    """Load user preferences, tolerating missing or invalid files."""
    path = user_config_path()
    if not path.exists():
        return UserConfig()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return UserConfig()
    if not isinstance(payload, dict):
        return UserConfig()
    locale = payload.get("locale")
    return UserConfig(locale=str(locale) if locale else None)


def save_user_config(config: UserConfig) -> Path:
    """Persist user preferences and return the written path."""
    path = user_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {}
    if config.locale:
        payload["locale"] = config.locale
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
