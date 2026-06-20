"""Bootstrap model registry.

No model download or inference integration lives here in v0.1.0.
"""

from __future__ import annotations

from xingyu_lyrics_aligner.schemas import ModelManifest


def known_model_slots() -> list[ModelManifest]:
    """Return model slots reserved for future implementation."""
    return [
        ModelManifest(
            model_id="forced-aligner",
            name="Forced Aligner",
            version="unimplemented",
            required=False,
            implemented=False,
        ),
        ModelManifest(
            model_id="vocal-separator",
            name="Vocal Separator",
            version="unimplemented",
            required=False,
            implemented=False,
        ),
    ]
