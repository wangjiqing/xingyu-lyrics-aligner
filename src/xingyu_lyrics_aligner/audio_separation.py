"""Reusable Demucs two-stem separation without exposing its private layout."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import threading
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path


class AudioSeparationError(RuntimeError):
    """A stable failure raised when two-track separation cannot complete."""


@dataclass(frozen=True)
class SeparatedAudio:
    """Both tracks produced by one Demucs invocation."""

    vocals: Path
    accompaniment: Path


_active_process_lock = threading.Lock()
_active_process: subprocess.Popen[str] | None = None


def terminate_active_separation(*, timeout_seconds: float = 5.0) -> None:
    """Terminate the currently registered Demucs child without touching unrelated PIDs."""

    with _active_process_lock:
        process = _active_process
    if process is None or process.poll() is not None:
        return
    with suppress(ProcessLookupError):
        process.terminate()
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        with suppress(ProcessLookupError):
            process.kill()
        with suppress(subprocess.TimeoutExpired):
            process.wait(timeout=timeout_seconds)


def separate_vocals_and_accompaniment(audio_path: Path, work_dir: Path) -> SeparatedAudio:
    """Run Demucs once and return its verified vocals and accompaniment tracks."""

    if importlib.util.find_spec("demucs") is None:
        raise AudioSeparationError("Demucs is not installed in the selected Python runtime.")

    private_output = work_dir / "_demucs"
    # A crashed attempt can leave other model directories behind. Demucs writes
    # no attempt identity into its output, so stale files must never be reused.
    shutil.rmtree(private_output, ignore_errors=True)
    command = [
        sys.executable,
        "-m",
        "demucs",
    ]
    managed_repo = os.environ.get("XINGYU_DEMUCS_MODEL_REPO")
    if managed_repo:
        command.extend(["--repo", managed_repo, "-n", "htdemucs"])
    command.extend(
        [
            "--two-stems",
            "vocals",
            "-o",
            str(private_output),
            str(audio_path),
        ]
    )
    global _active_process
    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=False,
    )
    with _active_process_lock:
        _active_process = process
    try:
        _stdout, stderr = process.communicate()
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, command, stderr=stderr)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr or ""
        if "TorchCodec is required" in stderr or "No module named 'torchcodec'" in stderr:
            raise AudioSeparationError(
                "Demucs could not save WAV output because TorchCodec is unavailable."
            ) from exc
        raise AudioSeparationError(
            f"Demucs failed with exit code {exc.returncode}: {stderr.strip()}"
        ) from exc
    finally:
        with _active_process_lock:
            if _active_process is process:
                _active_process = None

    stem_dir = _find_stem_directory(private_output, audio_path.stem)
    vocals = stem_dir / "vocals.wav"
    accompaniment = stem_dir / "no_vocals.wav"
    missing = [path.name for path in (vocals, accompaniment) if not path.is_file()]
    if missing:
        raise AudioSeparationError(
            "Demucs completed without both required tracks: " + ", ".join(missing)
        )
    return SeparatedAudio(vocals=vocals, accompaniment=accompaniment)


def export_separated_audio(
    separated: SeparatedAudio,
    output_dir: Path,
    *,
    export_vocals: bool,
    export_accompaniment: bool,
) -> dict[str, Path]:
    """Copy selected tracks to stable product-level result paths."""

    audio_dir = output_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, Path] = {}
    if export_vocals:
        vocals = audio_dir / "vocals.wav"
        shutil.copy2(separated.vocals, vocals)
        files["vocals"] = vocals
    if export_accompaniment:
        accompaniment = audio_dir / "accompaniment.wav"
        shutil.copy2(separated.accompaniment, accompaniment)
        files["accompaniment"] = accompaniment
    return files


def _find_stem_directory(private_output: Path, stem_name: str) -> Path:
    # The command does not override ``-n``, so Demucs 4 uses its htdemucs
    # default. Do not select another model directory left by an older attempt.
    stem_dir = private_output / "htdemucs" / stem_name
    if not stem_dir.is_dir():
        raise AudioSeparationError(
            "Demucs completed but its two-stem output directory was not found."
        )
    return stem_dir
