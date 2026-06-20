"""Project directory conventions.

These paths are intentionally based on the CLI runtime working directory.
That is convenient for local-first commands run beside media files, but a
future library API may need an environment variable or explicit config file
to override the project root.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path.cwd()
MODELS_DIR = PROJECT_ROOT / "models"
CACHE_DIR = PROJECT_ROOT / "cache"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
DOCS_DIR = PROJECT_ROOT / "docs"
