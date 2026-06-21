"""Audio loading for CTC alignment."""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path

from xingyu_lyrics_aligner.device import detect_device_capabilities


@dataclass(frozen=True)
class LoadedAudio:
    """WhisperX-compatible waveform and duration."""

    samples: object
    duration_seconds: float


def validate_audio_prerequisites(audio_path: Path) -> None:
    """Validate audio input and ffmpeg before model work starts."""
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file does not exist: {audio_path}")
    if not audio_path.is_file():
        raise ValueError(f"Audio path is not a file: {audio_path}")
    if detect_device_capabilities().ffmpeg_path is None:
        raise RuntimeError("FFmpeg is required for audio loading but was not found on PATH.")
    if importlib.util.find_spec("whisperx") is None:
        raise RuntimeError(
            "WhisperX is not installed. Install the alignment runtime before running align."
        )


def load_audio(audio_path: Path) -> LoadedAudio:
    """Load audio with WhisperX without invoking transcription."""
    validate_audio_prerequisites(audio_path)
    import whisperx

    samples = whisperx.load_audio(str(audio_path))
    return LoadedAudio(samples=samples, duration_seconds=len(samples) / 16000.0)
