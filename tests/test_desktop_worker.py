from __future__ import annotations

import json
import platform
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from pytest import MonkeyPatch

from xingyu_lyrics_aligner import __version__, audio_separation
from xingyu_lyrics_aligner import worker as worker_module
from xingyu_lyrics_aligner.alignment.pipeline import (
    AlignmentPipelineStage,
    AlignRunResult,
)
from xingyu_lyrics_aligner.alignment.swlrc_exporter import SwlrcExportStats
from xingyu_lyrics_aligner.audio_separation import SeparatedAudio
from xingyu_lyrics_aligner.device import DeviceStrategy
from xingyu_lyrics_aligner.schemas.alignment import (
    AlignmentDocument,
    AlignmentSource,
    ReportDocument,
)
from xingyu_lyrics_aligner.worker import (
    WorkerDesktopExportsV3,
    WorkerError,
    WorkerStatus,
    load_request,
    read_events_jsonl,
    remove_unselected_desktop_outputs,
    run_worker,
)


def test_remove_unselected_outputs_enforces_result_containment(tmp_path: Path) -> None:
    jobs, _music, job = create_desktop_job(tmp_path, exports={"lrc": True, "swlrc": False})
    request = load_request(job)
    output = job / "result"
    output.mkdir()
    valid = output / "lyrics.swlrc"
    valid.write_text("valid")
    remove_unselected_desktop_outputs(request, {"swlrc": valid}, output)
    assert not valid.exists()

    outside = tmp_path / "outside.swlrc"
    outside.write_text("preserved")
    with pytest.raises(WorkerError, match="outside"):
        remove_unselected_desktop_outputs(request, {"swlrc": outside}, output)
    assert outside.read_text() == "preserved"

    link = output / "linked.swlrc"
    link.symlink_to(outside)
    with pytest.raises(WorkerError, match="symlink"):
        remove_unselected_desktop_outputs(request, {"swlrc": link}, output)
    assert outside.read_text() == "preserved"


def create_desktop_job(
    tmp_path: Path,
    *,
    exports: dict[str, bool] | None = None,
    lyrics_path: Path | None = None,
    audio_path: Path | None = None,
) -> tuple[Path, Path, Path]:
    jobs = tmp_path / "jobs"
    music = tmp_path / "music"
    job = jobs / "desktop-001"
    job.mkdir(parents=True)
    music.mkdir()
    audio = audio_path or music / "歌曲 with space.flac"
    if audio_path is None:
        audio.write_bytes(b"audio")
    lyrics = lyrics_path or job / "trusted 歌词.txt"
    if lyrics_path is None:
        lyrics.write_text("星语\n", encoding="utf-8")
    request: dict[str, object] = {
        "schemaVersion": 3,
        "taskType": "DESKTOP_LYRIC_PROCESSING",
        "jobId": job.name,
        "audioPath": str(audio),
        "trustedLyricsPath": str(lyrics),
        "outputDir": str(job / "result"),
        "language": "zh",
        "device": "cpu",
    }
    if exports is not None:
        request["exports"] = exports
    (job / "request.json").write_text(json.dumps(request), encoding="utf-8")
    (job / "READY").write_text("", encoding="utf-8")
    return jobs, music, job


def fake_align(
    *, warnings: list[str] | None = None, before_export: Callable[[], None] | None = None
):
    def align_lyrics(**kwargs: Any) -> AlignRunResult:
        output = Path(kwargs["output_dir"])
        options = kwargs["options"]
        observer = options.stage_observer
        assert observer is not None
        observer(AlignmentPipelineStage.PREPARING_AUDIO)
        observer(AlignmentPipelineStage.LOADING_ALIGNMENT_MODEL)
        observer(AlignmentPipelineStage.ALIGNING)
        if before_export is not None:
            before_export()
        observer(AlignmentPipelineStage.EXPORTING_OUTPUTS)
        output.mkdir(parents=True, exist_ok=True)
        for name in ("alignment.json", "lyrics.lrc", "lyrics.swlrc", "report.json"):
            (output / name).write_text("{}\n", encoding="utf-8")
        source = AlignmentSource(
            audio_name="song.flac",
            alignment_model="fake-model",
            requested_device="cpu",
            actual_alignment_device="cpu",
        )
        report = ReportDocument(
            language="zh",
            source=source,
            line_count=1,
            aligned_or_partial_lines=1,
            input_alignment_characters=2,
            timed_character_entries=2,
            missing_character_timestamps=0,
            character_count_matches=True,
            non_monotonic_line_count=0,
            status_counts={},
            warnings=warnings or [],
        )
        return AlignRunResult(
            alignment=AlignmentDocument(language="zh", source=source, lines=[]),
            report=report,
            output_dir=output,
            swlrc=SwlrcExportStats(
                token_count=2,
                estimated_token_count=0,
                skipped_line_count=0,
                warnings=[],
            ),
        )

    return align_lyrics


def fake_separator(counter: list[int]):
    def separate(audio: Path, work: Path) -> SeparatedAudio:
        counter.append(1)
        private = work / "_demucs" / "htdemucs" / audio.stem
        private.mkdir(parents=True)
        vocals = private / "vocals.wav"
        accompaniment = private / "no_vocals.wav"
        vocals.write_bytes(b"vocals")
        accompaniment.write_bytes(b"accompaniment")
        return SeparatedAudio(vocals=vocals, accompaniment=accompaniment)

    return separate


def run_desktop(
    monkeypatch: MonkeyPatch,
    jobs: Path,
    music: Path,
    *,
    align: Callable[..., AlignRunResult] | None = None,
    separation_calls: list[int] | None = None,
) -> None:
    monkeypatch.setattr("xingyu_lyrics_aligner.worker.align_lyrics", align or fake_align())
    calls = separation_calls if separation_calls is not None else []
    monkeypatch.setattr(
        "xingyu_lyrics_aligner.worker.separate_vocals_and_accompaniment",
        fake_separator(calls),
    )
    run_worker(jobs_dir=jobs, music_dir=music, once=True, device=DeviceStrategy.CPU)


def read_status(job: Path) -> dict[str, Any]:
    return json.loads((job / "status.json").read_text(encoding="utf-8"))


def test_valid_desktop_request_and_export_defaults(tmp_path: Path) -> None:
    _, _, job = create_desktop_job(tmp_path)

    request = load_request(job)

    assert request.task_type == "DESKTOP_LYRIC_PROCESSING"
    assert request.exports.lrc is True
    assert request.exports.swlrc is True


def test_desktop_exports_require_lrc_or_swlrc() -> None:
    with pytest.raises(ValidationError, match="At least one"):
        WorkerDesktopExportsV3(lrc=False, swlrc=False, vocals=True)


@pytest.mark.parametrize(
    ("exports", "expected"),
    [
        ({"lrc": True, "swlrc": False}, {"LRC"}),
        ({"lrc": False, "swlrc": True}, {"SWLRC"}),
        ({"vocals": True}, {"LRC", "SWLRC", "VOCALS"}),
        ({"accompaniment": True}, {"LRC", "SWLRC", "ACCOMPANIMENT"}),
    ],
)
def test_desktop_export_combinations(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    exports: dict[str, bool],
    expected: set[str],
) -> None:
    jobs, music, job = create_desktop_job(tmp_path, exports=exports)
    run_desktop(monkeypatch, jobs, music)

    status = read_status(job)
    assert status["state"] == WorkerStatus.SUCCEEDED
    assert {item["kind"] for item in status["result"]["artifacts"]} == expected


def test_missing_trusted_lyrics_is_structured_failure(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    missing = tmp_path / "jobs" / "desktop-001" / "missing.txt"
    jobs, music, job = create_desktop_job(tmp_path, lyrics_path=missing)
    run_desktop(monkeypatch, jobs, music)

    status = read_status(job)
    assert status["state"] == WorkerStatus.FAILED
    assert status["error"]["code"] == "PATH_MISSING"


def test_desktop_rejects_trusted_lyrics_escape(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("星语\n", encoding="utf-8")
    jobs, music, job = create_desktop_job(tmp_path, lyrics_path=outside)
    run_desktop(monkeypatch, jobs, music)

    assert read_status(job)["error"]["code"] == "PATH_OUTSIDE_ALLOWED_ROOT"


def test_desktop_rejects_trusted_lyrics_symlink_escape(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("星语\n", encoding="utf-8")
    jobs, music, job = create_desktop_job(tmp_path)
    lyrics_link = job / "linked-lyrics.txt"
    lyrics_link.symlink_to(outside)
    request = json.loads((job / "request.json").read_text(encoding="utf-8"))
    request["trustedLyricsPath"] = str(lyrics_link)
    (job / "request.json").write_text(json.dumps(request), encoding="utf-8")
    run_desktop(monkeypatch, jobs, music)

    assert read_status(job)["error"]["code"] == "PATH_OUTSIDE_ALLOWED_ROOT"


@pytest.mark.skipif(platform.system() != "Darwin", reason="macOS filesystem normalization")
def test_desktop_resolves_nfc_request_for_nfd_lyrics(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    jobs, music, job = create_desktop_job(tmp_path)
    nfc_name = unicodedata.normalize("NFC", "café-歌词.txt")
    nfd_name = unicodedata.normalize("NFD", nfc_name)
    disk_path = job / nfd_name
    disk_path.write_text("星语\n", encoding="utf-8")
    request = json.loads((job / "request.json").read_text(encoding="utf-8"))
    request["trustedLyricsPath"] = str(job / nfc_name)
    (job / "request.json").write_text(json.dumps(request), encoding="utf-8")
    run_desktop(monkeypatch, jobs, music)

    assert read_status(job)["state"] == WorkerStatus.SUCCEEDED


def test_no_audio_exports_never_calls_separator(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    jobs, music, job = create_desktop_job(tmp_path, exports={"lrc": True, "swlrc": True})
    calls: list[int] = []
    run_desktop(monkeypatch, jobs, music, separation_calls=calls)

    assert calls == []
    assert read_status(job)["state"] == WorkerStatus.SUCCEEDED


def test_desktop_removes_stale_intermediate_before_separation(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    jobs, music, job = create_desktop_job(tmp_path, exports={"vocals": True})
    stale = job / "intermediate" / "_demucs" / "old-model" / "old-song"
    stale.mkdir(parents=True)
    (stale / "vocals.wav").write_bytes(b"stale")

    def separate(_: Path, work: Path) -> SeparatedAudio:
        assert not stale.exists()
        current = work / "current"
        current.mkdir(parents=True)
        vocals = current / "vocals.wav"
        accompaniment = current / "no_vocals.wav"
        vocals.write_bytes(b"current vocals")
        accompaniment.write_bytes(b"current accompaniment")
        return SeparatedAudio(vocals=vocals, accompaniment=accompaniment)

    monkeypatch.setattr("xingyu_lyrics_aligner.worker.align_lyrics", fake_align())
    monkeypatch.setattr("xingyu_lyrics_aligner.worker.separate_vocals_and_accompaniment", separate)
    run_worker(jobs_dir=jobs, music_dir=music, once=True)

    assert read_status(job)["state"] == WorkerStatus.SUCCEEDED


def test_selected_tracks_call_separator_once_and_map_all_artifacts(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    exports = {
        "lrc": True,
        "swlrc": True,
        "vocals": True,
        "accompaniment": True,
        "alignmentJson": True,
        "reportJson": True,
    }
    jobs, music, job = create_desktop_job(tmp_path, exports=exports)
    calls: list[int] = []
    run_desktop(monkeypatch, jobs, music, separation_calls=calls)

    status = read_status(job)
    assert calls == [1]
    assert status["result"]["files"]["vocals"].endswith("result/audio/vocals.wav")
    assert status["result"]["files"]["accompaniment"].endswith("result/audio/accompaniment.wav")
    assert len(status["result"]["artifacts"]) == 6
    assert not (job / "intermediate").exists()
    assert (job / "result" / "audio" / "vocals.wav").read_bytes() == b"vocals"
    assert (job / "result" / "audio" / "accompaniment.wav").read_bytes() == b"accompaniment"


def test_desktop_integration_uses_shared_demucs_file_discovery(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    jobs, music, job = create_desktop_job(
        tmp_path,
        exports={"lrc": True, "swlrc": True, "vocals": True, "accompaniment": True},
    )
    demucs_calls: list[list[str]] = []

    class DemucsProcess:
        returncode = 0

        def __init__(self, command: list[str], **_: object) -> None:
            demucs_calls.append(command)
            self.command = command

        def communicate(self) -> tuple[str, str]:
            output = Path(self.command[self.command.index("-o") + 1])
            audio = Path(self.command[-1])
            stem = output / "htdemucs" / audio.stem
            stem.mkdir(parents=True)
            (stem / "vocals.wav").write_bytes(b"real-path-vocals")
            (stem / "no_vocals.wav").write_bytes(b"real-path-accompaniment")
            return "", ""

    monkeypatch.setattr("xingyu_lyrics_aligner.worker.align_lyrics", fake_align())
    monkeypatch.setattr(audio_separation.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(audio_separation.subprocess, "Popen", DemucsProcess)
    run_worker(jobs_dir=jobs, music_dir=music, once=True)

    assert len(demucs_calls) == 1
    assert (job / "result" / "audio" / "vocals.wav").read_bytes() == b"real-path-vocals"
    assert (job / "result" / "audio" / "accompaniment.wav").read_bytes() == (
        b"real-path-accompaniment"
    )


def test_needs_review_keeps_artifacts_and_emits_warning(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    jobs, music, job = create_desktop_job(tmp_path)
    run_desktop(monkeypatch, jobs, music, align=fake_align(warnings=["review_this"]))

    status = read_status(job)
    events = read_events_jsonl(job / "events.jsonl")
    assert status["state"] == WorkerStatus.NEEDS_REVIEW
    assert status["result"]["artifacts"]
    warning_events = [event for event in events if event["type"] == "WARNING"]
    assert warning_events[0]["details"]["source"] == "alignment_result"


def test_preflight_cancellation_is_its_own_terminal_state(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    jobs, music, job = create_desktop_job(tmp_path)
    (job / "CANCEL_REQUESTED").write_text("", encoding="utf-8")
    run_desktop(monkeypatch, jobs, music)

    status = read_status(job)
    events = read_events_jsonl(job / "events.jsonl")
    assert status["state"] == WorkerStatus.CANCELLED
    assert status["error"] is None
    assert (job / "CANCELLED").exists()
    assert not any((job / marker).exists() for marker in ("SUCCEEDED", "FAILED", "NEEDS_REVIEW"))
    assert events[-1]["type"] == "TASK_CANCELLED"


def test_cancellation_before_export_stops_other_terminal_outcomes(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    jobs, music, job = create_desktop_job(tmp_path)

    def request_cancel() -> None:
        (job / "CANCEL_REQUESTED").write_text("", encoding="utf-8")

    run_desktop(monkeypatch, jobs, music, align=fake_align(before_export=request_cancel))

    status = read_status(job)
    assert status["state"] == WorkerStatus.CANCELLED
    assert status["result"] is None
    assert not any((job / marker).exists() for marker in ("SUCCEEDED", "FAILED", "NEEDS_REVIEW"))


def test_cancellation_after_separation_stops_before_alignment(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    jobs, music, job = create_desktop_job(tmp_path, exports={"vocals": True})
    alignment_called = False

    def separate(audio: Path, work: Path) -> SeparatedAudio:
        private = work / "private"
        private.mkdir(parents=True)
        vocals = private / "vocals.wav"
        accompaniment = private / "no_vocals.wav"
        vocals.write_bytes(b"vocals")
        accompaniment.write_bytes(b"accompaniment")
        (job / "CANCEL_REQUESTED").write_text("", encoding="utf-8")
        return SeparatedAudio(vocals=vocals, accompaniment=accompaniment)

    def align(**_: Any) -> AlignRunResult:
        nonlocal alignment_called
        alignment_called = True
        raise AssertionError("alignment must not start after cancellation")

    monkeypatch.setattr("xingyu_lyrics_aligner.worker.align_lyrics", align)
    monkeypatch.setattr("xingyu_lyrics_aligner.worker.separate_vocals_and_accompaniment", separate)
    run_worker(jobs_dir=jobs, music_dir=music, once=True)

    assert alignment_called is False
    assert read_status(job)["state"] == WorkerStatus.CANCELLED
    assert not (job / "intermediate").exists()


def test_desktop_stage_progress_runtime_and_legacy_files_contract(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    jobs, music, job = create_desktop_job(tmp_path)
    run_desktop(monkeypatch, jobs, music)

    status = read_status(job)
    events = read_events_jsonl(job / "events.jsonl")
    stages = [event["stage"] for event in events if event["type"] == "STAGE_STARTED"]
    assert stages == [
        "PREPARING_AUDIO",
        "LOADING_ALIGNMENT_MODEL",
        "ALIGNING",
        "EXPORTING_OUTPUTS",
        "QUALITY_CHECKING",
        "FINALIZING",
    ]
    assert status["progress"] == {"kind": "COMPLETE", "current": 1, "total": 1, "fraction": 1.0}
    assert status["result"]["files"]
    assert status["runtime"] == {
        "workerVersion": __version__,
        "pythonVersion": platform.python_version(),
        "platform": f"{platform.system()}-{platform.machine()}",
    }


def test_running_progress_remains_indeterminate(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    jobs, music, job = create_desktop_job(tmp_path)
    observed: list[dict[str, object]] = []

    def inspect_before_export() -> None:
        observed.append(read_status(job)["progress"])

    run_desktop(monkeypatch, jobs, music, align=fake_align(before_export=inspect_before_export))

    assert observed == [{"kind": "INDETERMINATE", "current": None, "total": None, "fraction": None}]


def test_cancellation_during_artifact_commit_finishes_verified_result(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    jobs, music, job = create_desktop_job(tmp_path)
    original = worker_module.build_desktop_artifacts

    def build_and_request_cancel(job_dir: Path, files: dict[str, Path]):
        (job / "CANCEL_REQUESTED").write_text("", encoding="utf-8")
        return original(job_dir, files)

    monkeypatch.setattr(worker_module, "build_desktop_artifacts", build_and_request_cancel)
    run_desktop(monkeypatch, jobs, music)

    status = read_status(job)
    assert status["state"] == WorkerStatus.SUCCEEDED
    assert status["result"]["artifacts"]
    assert not (job / "CANCELLED").exists()


def test_worker_error_during_artifact_commit_wins_over_late_cancel(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    jobs, music, job = create_desktop_job(tmp_path)

    def fail_and_request_cancel(_: Path, __: dict[str, Path]):
        (job / "CANCEL_REQUESTED").write_text("", encoding="utf-8")
        raise WorkerError("OUTPUT_MISSING", "Artifact disappeared during commit.")

    monkeypatch.setattr(worker_module, "build_desktop_artifacts", fail_and_request_cancel)
    run_desktop(monkeypatch, jobs, music)

    status = read_status(job)
    assert status["state"] == WorkerStatus.FAILED
    assert status["error"]["code"] == "OUTPUT_MISSING"
    assert not (job / "CANCELLED").exists()


def test_cancel_requested_after_quality_check_does_not_override_success(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    jobs, music, job = create_desktop_job(tmp_path)
    original = worker_module.classify_result

    def classify_and_request_cancel(*args: object, **kwargs: object) -> WorkerStatus:
        status = original(*args, **kwargs)
        (job / "CANCEL_REQUESTED").write_text("", encoding="utf-8")
        return status

    monkeypatch.setattr(worker_module, "classify_result", classify_and_request_cancel)
    run_desktop(monkeypatch, jobs, music)

    assert read_status(job)["state"] == WorkerStatus.SUCCEEDED
    assert not (job / "CANCELLED").exists()


def test_existing_schema_v3_alignment_request_still_loads(tmp_path: Path) -> None:
    jobs = tmp_path / "jobs"
    job = jobs / "legacy"
    job.mkdir(parents=True)
    request = {
        "schemaVersion": 3,
        "taskType": "LYRICS_ALIGNMENT",
        "jobId": "legacy",
        "audioPath": "/music/song.flac",
        "lyricsPath": str(job / "lyrics.txt"),
        "outputDir": str(job / "result"),
    }
    (job / "request.json").write_text(json.dumps(request), encoding="utf-8")

    assert load_request(job).task_type == "LYRICS_ALIGNMENT"


def test_invalid_desktop_request_is_reported_by_loader(tmp_path: Path) -> None:
    _, _, job = create_desktop_job(tmp_path, exports={"lrc": False, "swlrc": False})

    with pytest.raises(WorkerError, match="At least one"):
        load_request(job)


@pytest.mark.parametrize("target_inside", [False, True])
def test_claim_rejects_symlink_job_without_touching_target(
    tmp_path: Path, target_inside: bool
) -> None:
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    target = (jobs / "holder" / "target") if target_inside else (tmp_path / "outside")
    target.parent.mkdir(exist_ok=True)
    target.mkdir()
    (target / "READY").write_text("ready", encoding="utf-8")
    (target / "request.json").write_text("{}", encoding="utf-8")
    (jobs / "linked").symlink_to(target, target_is_directory=True)

    assert worker_module.claim_next_job(jobs) is None
    assert (target / "READY").read_text(encoding="utf-8") == "ready"
    assert not (target / "RUNNING").exists()
    assert not (target / "status.json").exists()


@pytest.mark.parametrize("name", ["READY", "request.json"])
def test_claim_rejects_symlink_control_files(tmp_path: Path, name: str) -> None:
    jobs, _, job = create_desktop_job(tmp_path)
    outside = tmp_path / f"outside-{name}"
    outside.write_text("untouched", encoding="utf-8")
    (job / name).unlink()
    (job / name).symlink_to(outside)

    assert worker_module.claim_next_job(jobs) is None
    assert outside.read_text(encoding="utf-8") == "untouched"
    assert not (job / "RUNNING").exists()


def test_terminal_commit_ignores_event_and_marker_failures_after_status(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    job = tmp_path / "job"
    job.mkdir()
    payload = {"state": "SUCCEEDED"}
    monkeypatch.setattr(
        worker_module,
        "append_event",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("events")),
    )
    monkeypatch.setattr(
        worker_module,
        "write_terminal_marker",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("marker")),
    )

    worker_module.commit_terminal_status(
        job,
        payload,
        status=WorkerStatus.SUCCEEDED,
        event_type=worker_module.WorkerEventType.TASK_COMPLETED,
    )

    assert read_status(job)["state"] == "SUCCEEDED"
    assert not (job / "FAILED").exists()


def test_terminal_commit_does_not_create_marker_when_final_status_fails(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    job = tmp_path / "job"
    job.mkdir()
    monkeypatch.setattr(
        worker_module,
        "write_status",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(PermissionError("status")),
    )

    with pytest.raises(PermissionError, match="status"):
        worker_module.commit_terminal_status(
            job,
            {"state": "SUCCEEDED"},
            status=WorkerStatus.SUCCEEDED,
            event_type=worker_module.WorkerEventType.TASK_COMPLETED,
        )

    assert not any((job / state.value).exists() for state in worker_module.TERMINAL_STATUSES)


def test_terminal_marker_removes_all_conflicts(tmp_path: Path) -> None:
    job = tmp_path / "job"
    job.mkdir()
    for state in ("FAILED", "CANCELLED", "NEEDS_REVIEW"):
        (job / state).write_text("old", encoding="utf-8")

    worker_module.write_terminal_marker(job, WorkerStatus.SUCCEEDED)

    assert (job / "SUCCEEDED").is_file()
    assert not any((job / state).exists() for state in ("FAILED", "CANCELLED", "NEEDS_REVIEW"))
