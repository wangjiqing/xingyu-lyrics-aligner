from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from pytest import MonkeyPatch

from xingyu_lyrics_aligner.alignment.ctc import WhisperXCtcAligner
from xingyu_lyrics_aligner.device import DeviceStrategy


def test_explicit_alignment_model_load_is_idempotent(monkeypatch: MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def load_align_model(**kwargs: object) -> tuple[object, object]:
        calls.append(kwargs)
        return object(), object()

    monkeypatch.setitem(sys.modules, "whisperx", SimpleNamespace(load_align_model=load_align_model))
    aligner = WhisperXCtcAligner(language="zh", requested_device=DeviceStrategy.CPU)

    aligner.load()
    aligner.load()

    assert len(calls) == 1
    assert calls[0]["model_cache_only"] is True


def test_managed_alignment_model_directory_is_passed_to_whisperx(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[dict[str, object]] = []
    model = tmp_path / "中文 model with spaces"
    model.mkdir()
    monkeypatch.setenv("XINGYU_ALIGNMENT_MODEL_DIR", str(model))
    monkeypatch.setitem(
        sys.modules,
        "whisperx",
        SimpleNamespace(
            load_align_model=lambda **kwargs: (calls.append(kwargs) or object(), object())
        ),
    )

    WhisperXCtcAligner(language="zh", requested_device=DeviceStrategy.CPU).load()

    assert calls[0]["model_name"] == str(model)
    assert calls[0]["model_cache_only"] is True
