from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from pytest import MonkeyPatch
from typer.testing import CliRunner

from xingyu_lyrics_aligner.alignment.pipeline import AlignRunResult
from xingyu_lyrics_aligner.alignment.swlrc_exporter import SwlrcExportStats
from xingyu_lyrics_aligner.cli import app
from xingyu_lyrics_aligner.schemas.alignment import (
    AlignmentDocument,
    AlignmentSource,
    ReportDocument,
)
from xingyu_lyrics_aligner.worker import (
    WorkerStatus,
    claim_next_job,
    mark_abandoned_jobs,
    run_worker,
)

runner = CliRunner()


def test_worker_help_smoke() -> None:
    result = runner.invoke(app, ["worker", "run", "--help"], terminal_width=160)

    assert result.exit_code == 0
    assert "Usage:" in result.stdout


def test_worker_claims_legal_job_and_writes_succeeded(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    jobs = tmp_path / "jobs"
    music = tmp_path / "music"
    job = create_job(jobs, music)

    monkeypatch.setattr("xingyu_lyrics_aligner.worker.align_lyrics", fake_align_result(job))

    run_worker(
        jobs_dir=jobs,
        music_dir=music,
        once=True,
        estimated_token_review_threshold=10,
    )

    status = read_status(job)
    assert status["status"] == WorkerStatus.SUCCEEDED
    assert "attempt" in status
    assert status["result"]["success"] is True
    assert status["result"]["files"]["swlrc"] == str(job / "result" / "lyrics.swlrc")
    assert not (job / "READY").exists()
    assert (job / "RUNNING").exists()


def test_worker_marks_successful_low_quality_job_needs_review(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    jobs = tmp_path / "jobs"
    music = tmp_path / "music"
    job = create_job(jobs, music)

    monkeypatch.setattr(
        "xingyu_lyrics_aligner.worker.align_lyrics",
        fake_align_result(job, line_count=2, aligned_line_count=1, skipped_line_count=1),
    )

    run_worker(jobs_dir=jobs, music_dir=music, once=True)

    assert read_status(job)["status"] == WorkerStatus.NEEDS_REVIEW


def test_worker_rejects_paths_outside_allowed_roots(tmp_path: Path) -> None:
    jobs = tmp_path / "jobs"
    music = tmp_path / "music"
    job = create_job(jobs, music, audio_path=tmp_path / "outside.flac")

    run_worker(jobs_dir=jobs, music_dir=music, once=True)

    status = read_status(job)
    assert status["status"] == WorkerStatus.FAILED
    assert status["error"]["code"] == "PATH_OUTSIDE_ALLOWED_ROOT"
    assert json.loads((job / "status.json").read_text(encoding="utf-8")) == status


def test_worker_rejects_output_dir_outside_jobs(tmp_path: Path) -> None:
    jobs = tmp_path / "jobs"
    music = tmp_path / "music"
    job = create_job(jobs, music, output_dir=tmp_path / "outside-result")

    run_worker(jobs_dir=jobs, music_dir=music, once=True)

    status = read_status(job)
    assert status["status"] == WorkerStatus.FAILED
    assert status["error"]["code"] == "PATH_OUTSIDE_ALLOWED_ROOT"


def test_worker_failure_preserves_stderr_log(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    jobs = tmp_path / "jobs"
    music = tmp_path / "music"
    job = create_job(jobs, music)

    def fail_align(**_: object) -> AlignRunResult:
        raise RuntimeError("model cache is not ready")

    monkeypatch.setattr("xingyu_lyrics_aligner.worker.align_lyrics", fail_align)

    run_worker(jobs_dir=jobs, music_dir=music, once=True)

    status = read_status(job)
    assert status["status"] == WorkerStatus.FAILED
    assert status["error"]["code"] == "ALIGNMENT_FAILED"
    assert "model cache is not ready" in status["error"]["message"]
    assert "RuntimeError: model cache is not ready" in (job / "stderr.log").read_text(
        encoding="utf-8"
    )
    attempt_stderr = Path(cast(dict[str, str], status["attempt"])["stderr"])
    assert attempt_stderr.exists()
    assert "RuntimeError: model cache is not ready" in attempt_stderr.read_text(encoding="utf-8")


def test_worker_retry_preserves_previous_attempt_stderr(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    jobs = tmp_path / "jobs"
    music = tmp_path / "music"
    job = create_job(jobs, music)
    failures = iter(["first failure", "second failure"])

    def fail_align(**_: object) -> AlignRunResult:
        raise RuntimeError(next(failures))

    monkeypatch.setattr("xingyu_lyrics_aligner.worker.align_lyrics", fail_align)

    run_worker(jobs_dir=jobs, music_dir=music, once=True)
    first_status = read_status(job)
    first_attempt_stderr = Path(cast(dict[str, str], first_status["attempt"])["stderr"])

    (job / "RUNNING").unlink()
    (job / "READY").write_text("", encoding="utf-8")
    run_worker(jobs_dir=jobs, music_dir=music, once=True)

    second_status = read_status(job)
    second_attempt_stderr = Path(cast(dict[str, str], second_status["attempt"])["stderr"])
    assert first_attempt_stderr != second_attempt_stderr
    assert "RuntimeError: first failure" in first_attempt_stderr.read_text(encoding="utf-8")
    assert "RuntimeError: second failure" in second_attempt_stderr.read_text(encoding="utf-8")
    assert "RuntimeError: second failure" in (job / "stderr.log").read_text(encoding="utf-8")


def test_worker_missing_result_files_is_failed(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    jobs = tmp_path / "jobs"
    music = tmp_path / "music"
    job = create_job(jobs, music)

    monkeypatch.setattr(
        "xingyu_lyrics_aligner.worker.align_lyrics",
        fake_align_result(job, write_files=False),
    )

    run_worker(jobs_dir=jobs, music_dir=music, once=True)

    status = read_status(job)
    assert status["status"] == WorkerStatus.FAILED
    assert status["error"]["code"] == "OUTPUT_MISSING"
    assert "lyrics.swlrc" in status["error"]["message"]


def test_competing_claims_do_not_duplicate_same_ready_job(tmp_path: Path) -> None:
    jobs = tmp_path / "jobs"
    music = tmp_path / "music"
    create_job(jobs, music)

    first = claim_next_job(jobs)
    second = claim_next_job(jobs)

    assert first is not None
    assert second is None


def test_claim_does_not_overwrite_existing_running_marker(tmp_path: Path) -> None:
    jobs = tmp_path / "jobs"
    music = tmp_path / "music"
    job = create_job(jobs, music)
    (job / "RUNNING").write_text("already claimed\n", encoding="utf-8")

    claimed = claim_next_job(jobs)

    assert claimed is None
    assert (job / "READY").exists()
    assert (job / "RUNNING").read_text(encoding="utf-8") == "already claimed\n"


def test_stale_running_job_is_marked_abandoned(tmp_path: Path) -> None:
    jobs = tmp_path / "jobs"
    music = tmp_path / "music"
    job = create_job(jobs, music)
    (job / "READY").unlink()
    running = job / "RUNNING"
    running.write_text("", encoding="utf-8")
    old = time.time() - 10
    os.utime(running, (old, old))

    mark_abandoned_jobs(jobs, timeout_seconds=1)

    status = read_status(job)
    assert status["status"] == WorkerStatus.ABANDONED
    assert status["error"]["code"] == "RUNNING_TIMEOUT"
    assert (job / "ABANDONED").exists()


def create_job(
    jobs: Path,
    music: Path,
    *,
    audio_path: Path | None = None,
    lyrics_path: Path | None = None,
    output_dir: Path | None = None,
) -> Path:
    job = jobs / "job-001"
    job.mkdir(parents=True)
    music.mkdir(parents=True)
    audio = audio_path or music / "song.flac"
    lyrics = lyrics_path or job / "trusted-lyrics.txt"
    output = output_dir or job / "result"
    if audio == music / "song.flac":
        audio.write_bytes(b"fake")
    if lyrics == job / "trusted-lyrics.txt":
        lyrics.write_text("星语\n", encoding="utf-8")
    request = {
        "schemaVersion": 1,
        "jobId": "job-001",
        "audioPath": str(audio),
        "lyricsPath": str(lyrics),
        "outputDir": str(output),
        "language": "zh",
        "device": "cpu",
        "sectionManifestPath": None,
        "createdAt": "2026-06-28T00:00:00Z",
    }
    (job / "request.json").write_text(json.dumps(request), encoding="utf-8")
    (job / "READY").write_text("", encoding="utf-8")
    return job


def fake_align_result(
    job: Path,
    *,
    line_count: int = 1,
    aligned_line_count: int = 1,
    skipped_line_count: int = 0,
    write_files: bool = True,
) -> Callable[..., AlignRunResult]:
    def fake_align_lyrics(**_: object) -> AlignRunResult:
        output_dir = job / "result"
        if write_files:
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "alignment.json").write_text("{}\n", encoding="utf-8")
            (output_dir / "lyrics.lrc").write_text("", encoding="utf-8")
            (output_dir / "lyrics.swlrc").write_text("", encoding="utf-8")
            (output_dir / "report.json").write_text("{}\n", encoding="utf-8")
        source = AlignmentSource(
            audio_name="song.flac",
            alignment_model="fake-model",
            requested_device="cpu",
            actual_alignment_device="cpu",
        )
        alignment = AlignmentDocument(language="zh", source=source, lines=[])
        report = ReportDocument(
            language="zh",
            source=source,
            line_count=line_count,
            aligned_or_partial_lines=aligned_line_count,
            input_alignment_characters=1,
            timed_character_entries=1,
            missing_character_timestamps=0,
            character_count_matches=True,
            non_monotonic_line_count=0,
            status_counts={},
            warnings=[],
        )
        return AlignRunResult(
            alignment=alignment,
            report=report,
            output_dir=output_dir,
            swlrc=SwlrcExportStats(
                token_count=1,
                estimated_token_count=0,
                skipped_line_count=skipped_line_count,
                warnings=[],
            ),
        )

    return fake_align_lyrics


def read_status(job: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((job / "status.json").read_text(encoding="utf-8")))
