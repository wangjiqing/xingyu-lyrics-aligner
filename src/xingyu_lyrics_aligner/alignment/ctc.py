"""WhisperX CTC forced alignment wrapper.

This module intentionally does not expose or call WhisperX transcription APIs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from xingyu_lyrics_aligner.alignment.backmap import CharacterTiming
from xingyu_lyrics_aligner.device import DeviceStrategy, detect_torch_accelerators

DEFAULT_ALIGN_MODEL = "jonatasgrosman/wav2vec2-large-xlsr-53-chinese-zh-cn"


@dataclass(frozen=True)
class DeviceResolution:
    """Requested and actual alignment device."""

    requested: str
    actual: str
    warnings: list[str]


@dataclass(frozen=True)
class CtcSegment:
    """One trusted-text CTC alignment segment."""

    text: str
    start: float
    end: float
    id: str | None = None
    kind: str | None = None


class WhisperXCtcAligner:
    """Small wrapper around WhisperX alignment only."""

    def __init__(
        self,
        *,
        language: str,
        requested_device: DeviceStrategy,
        align_model_name: str = DEFAULT_ALIGN_MODEL,
    ) -> None:
        self.language = language
        self.align_model_name = align_model_name
        self.device = resolve_alignment_device(requested_device)
        self._align_model: Any | None = None
        self._metadata: Any | None = None

    def load(self) -> None:
        """Load the local cached alignment model, failing clearly if unavailable."""
        try:
            import whisperx
        except ImportError as exc:
            raise RuntimeError(
                "WhisperX is not installed. Install the alignment runtime before running align."
            ) from exc

        try:
            self._align_model, self._metadata = whisperx.load_align_model(
                language_code=self.language,
                device=self.device.actual,
                model_name=self.align_model_name,
                model_cache_only=True,
            )
        except Exception as exc:
            raise RuntimeError(
                "WhisperX alignment model is not available locally. "
                "Run `xingyu-align models pull --language zh` to prepare the required "
                "alignment model before aligning."
            ) from exc

    def align(self, segment: CtcSegment, audio: object) -> list[CharacterTiming]:
        """Align one trusted-text segment and return compact character timings."""
        if self._align_model is None or self._metadata is None:
            self.load()
        import whisperx

        raw_segments = [{"text": segment.text, "start": segment.start, "end": segment.end}]
        result = whisperx.align(
            raw_segments,
            self._align_model,
            self._metadata,
            audio,
            self.device.actual,
            return_char_alignments=True,
        )
        return collect_char_entries(result)


def resolve_alignment_device(requested_device: DeviceStrategy) -> DeviceResolution:
    """Resolve user-facing device request to the actual WhisperX alignment device."""
    cuda_available, _mps_available = detect_torch_accelerators()
    requested = requested_device.value
    warnings: list[str] = []

    if requested_device == DeviceStrategy.CPU:
        return DeviceResolution(requested=requested, actual="cpu", warnings=warnings)
    if requested_device == DeviceStrategy.CUDA:
        if not cuda_available:
            raise RuntimeError("CUDA was requested but torch does not report CUDA availability.")
        return DeviceResolution(requested=requested, actual="cuda", warnings=warnings)
    if requested_device == DeviceStrategy.MPS:
        warnings.append("mps_alignment_cpu_fallback")
        return DeviceResolution(requested=requested, actual="cpu", warnings=warnings)
    if cuda_available:
        return DeviceResolution(requested=requested, actual="cuda", warnings=warnings)
    return DeviceResolution(requested=requested, actual="cpu", warnings=warnings)


def collect_char_entries(align_result: dict[str, Any]) -> list[CharacterTiming]:
    """Extract compact character timing entries from WhisperX alignment output."""
    entries: list[CharacterTiming] = []
    for segment in align_result.get("segments", []):
        chars = segment.get("chars")
        if chars:
            for char in chars:
                text = char.get("char", "")
                if text:
                    entries.append(
                        CharacterTiming(
                            text=text,
                            start=char.get("start"),
                            end=char.get("end"),
                            score=char.get("score"),
                        )
                    )
            continue
        for word in segment.get("words", []):
            text = word.get("word", "")
            if text:
                entries.append(
                    CharacterTiming(
                        text=text,
                        start=word.get("start"),
                        end=word.get("end"),
                        score=word.get("score"),
                    )
                )
    return entries
