"""Local model registry metadata.

No model download is performed by this registry.
"""

from __future__ import annotations

from xingyu_lyrics_aligner.schemas import ModelManifest


def known_model_slots() -> list[ModelManifest]:
    """Return known local model slots."""
    return [
        ModelManifest(
            model_id="forced-aligner",
            name="Forced Aligner",
            version="whisperx-ctc",
            required=True,
            implemented=True,
            license="model-dependent",
            source_url="https://huggingface.co/jonatasgrosman/wav2vec2-large-xlsr-53-chinese-zh-cn",
        ),
        ModelManifest(
            model_id="vocal-separator",
            name="Vocal Separator",
            version="unimplemented",
            required=False,
            implemented=False,
        ),
    ]
