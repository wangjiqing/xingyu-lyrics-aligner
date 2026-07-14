"""Shared-directory worker for Docker Compose integrations."""

from __future__ import annotations

import json
import os
import platform
import shutil
import signal
import threading
import time
import traceback
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from xingyu_lyrics_aligner import __version__
from xingyu_lyrics_aligner.alignment.pipeline import AlignmentPipelineStage
from xingyu_lyrics_aligner.api import AlignLyricsOptions, align_lyrics
from xingyu_lyrics_aligner.audio_separation import (
    AudioSeparationError,
    export_separated_audio,
    separate_vocals_and_accompaniment,
    terminate_active_separation,
)
from xingyu_lyrics_aligner.candidate_lyrics.config import (
    DraftConfigError,
    DraftExtractionConfig,
    requested_draft_config_json,
    resolve_draft_extraction_config,
)
from xingyu_lyrics_aligner.candidate_lyrics.transcription import (
    CandidateLyricsExtractionRequest,
    CandidateLyricsExtractionService,
)
from xingyu_lyrics_aligner.commands.align import align_error_code, align_json_result_payload
from xingyu_lyrics_aligner.device import DeviceStrategy
from xingyu_lyrics_aligner.schemas.artifacts import ArtifactKind, ResultArtifact, ResultArtifacts


class WorkerStatus(StrEnum):
    """Stable status values written to status.json."""

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    FAILED = "FAILED"
    ABANDONED = "ABANDONED"
    CANCELLED = "CANCELLED"


class WorkerTaskType(StrEnum):
    """Stable Worker task types across supported request schema versions."""

    LYRICS_ALIGNMENT = "LYRICS_ALIGNMENT"
    LYRIC_DRAFT_EXTRACTION = "LYRIC_DRAFT_EXTRACTION"
    DESKTOP_LYRIC_PROCESSING = "DESKTOP_LYRIC_PROCESSING"


class WorkerStage(StrEnum):
    """Stable machine-readable stage codes."""

    VALIDATING_REQUEST = "VALIDATING_REQUEST"
    PREPARING_INPUT = "PREPARING_INPUT"
    PREPARING_AUDIO = "PREPARING_AUDIO"
    SEPARATING_VOCALS = "SEPARATING_VOCALS"
    LOADING_ALIGNMENT_MODEL = "LOADING_ALIGNMENT_MODEL"
    LOADING_ASR_MODEL = "LOADING_ASR_MODEL"
    PREPARING_ALIGNMENT_TEXT = "PREPARING_ALIGNMENT_TEXT"
    ALIGNING = "ALIGNING"
    TRANSCRIBING = "TRANSCRIBING"
    POSTPROCESSING_TRANSCRIPT = "POSTPROCESSING_TRANSCRIPT"
    EXPORTING_OUTPUTS = "EXPORTING_OUTPUTS"
    WRITING_OUTPUTS = "WRITING_OUTPUTS"
    QUALITY_CHECKING = "QUALITY_CHECKING"
    FINALIZING = "FINALIZING"


class WorkerEventType(StrEnum):
    """Stable events appended to events.jsonl."""

    TASK_ACCEPTED = "TASK_ACCEPTED"
    STAGE_STARTED = "STAGE_STARTED"
    STAGE_PROGRESS = "STAGE_PROGRESS"
    WARNING = "WARNING"
    TASK_COMPLETED = "TASK_COMPLETED"
    TASK_NEEDS_REVIEW = "TASK_NEEDS_REVIEW"
    TASK_FAILED = "TASK_FAILED"
    TASK_ABANDONED = "TASK_ABANDONED"
    TASK_CANCELLED = "TASK_CANCELLED"


class WorkerRequestV1(BaseModel):
    """v0.3.0 alignment request contract for /jobs/{jobId}/request.json."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = Field(alias="schemaVersion")
    job_id: str = Field(alias="jobId", min_length=1)
    audio_path: Path = Field(alias="audioPath")
    lyrics_path: Path = Field(alias="lyricsPath")
    output_dir: Path = Field(alias="outputDir")
    language: str = "zh"
    device: DeviceStrategy = DeviceStrategy.CPU
    section_manifest_path: Path | None = Field(default=None, alias="sectionManifestPath")
    created_at: str | None = Field(default=None, alias="createdAt")

    @property
    def task_type(self) -> WorkerTaskType:
        return WorkerTaskType.LYRICS_ALIGNMENT


class WorkerAlignmentRequestV2(BaseModel):
    """schemaVersion 2 trusted-lyrics alignment request."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[2] = Field(alias="schemaVersion")
    job_id: str = Field(alias="jobId", min_length=1)
    task_type: Literal[WorkerTaskType.LYRICS_ALIGNMENT] = Field(alias="taskType")
    audio_path: Path = Field(alias="audioPath")
    lyrics_path: Path = Field(alias="lyricsPath")
    output_dir: Path = Field(alias="outputDir")
    language: str = "zh"
    device: DeviceStrategy = DeviceStrategy.CPU
    section_manifest_path: Path | None = Field(default=None, alias="sectionManifestPath")
    created_at: str | None = Field(default=None, alias="createdAt")


class WorkerDraftExtractionRequestV2(BaseModel):
    """schemaVersion 2 candidate lyric draft extraction request."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[2] = Field(alias="schemaVersion")
    job_id: str = Field(alias="jobId", min_length=1)
    task_type: Literal[WorkerTaskType.LYRIC_DRAFT_EXTRACTION] = Field(alias="taskType")
    audio_path: Path = Field(alias="audioPath")
    output_dir: Path = Field(alias="outputDir")
    language: str = "zh"
    device: DeviceStrategy = DeviceStrategy.CPU
    asr_model: str = Field(default="medium", alias="asrModel")
    skip_separation: bool = Field(default=False, alias="skipSeparation")
    vad_filter: bool = Field(default=True, alias="vadFilter")
    condition_on_previous_text: bool = Field(default=False, alias="conditionOnPreviousText")
    keep_suspected_metadata: bool = Field(default=False, alias="keepSuspectedMetadata")
    retain_intermediate: bool = Field(default=False, alias="retainIntermediate")
    created_at: str | None = Field(default=None, alias="createdAt")


class WorkerDraftOverridesV3(BaseModel):
    """Explicit schemaVersion 3 draft extraction advanced overrides."""

    model_config = ConfigDict(extra="forbid")

    asr_model: str | None = Field(default=None, alias="asrModel")
    skip_separation: bool | None = Field(default=None, alias="skipSeparation")
    vad_filter: bool | None = Field(default=None, alias="vadFilter")
    condition_on_previous_text: bool | None = Field(
        default=None,
        alias="conditionOnPreviousText",
    )
    keep_suspected_metadata: bool | None = Field(default=None, alias="keepSuspectedMetadata")
    retain_intermediate: bool | None = Field(default=None, alias="retainIntermediate")

    def to_resolver_overrides(self) -> dict[str, object | None]:
        return {
            "asrModel": self.asr_model,
            "skipSeparation": self.skip_separation,
            "vadFilter": self.vad_filter,
            "conditionOnPreviousText": self.condition_on_previous_text,
            "keepSuspectedMetadata": self.keep_suspected_metadata,
            "retainIntermediate": self.retain_intermediate,
        }


class WorkerAlignmentRequestV3(BaseModel):
    """schemaVersion 3 trusted-lyrics alignment request."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[3] = Field(alias="schemaVersion")
    job_id: str = Field(alias="jobId", min_length=1)
    task_type: Literal[WorkerTaskType.LYRICS_ALIGNMENT] = Field(alias="taskType")
    audio_path: Path = Field(alias="audioPath")
    lyrics_path: Path = Field(alias="lyricsPath")
    output_dir: Path = Field(alias="outputDir")
    language: str = "zh"
    device: DeviceStrategy = DeviceStrategy.CPU
    section_manifest_path: Path | None = Field(default=None, alias="sectionManifestPath")
    created_at: str | None = Field(default=None, alias="createdAt")


class WorkerDraftExtractionRequestV3(BaseModel):
    """schemaVersion 3 candidate lyric draft extraction request."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[3] = Field(alias="schemaVersion")
    job_id: str = Field(alias="jobId", min_length=1)
    task_type: Literal[WorkerTaskType.LYRIC_DRAFT_EXTRACTION] = Field(alias="taskType")
    audio_path: Path = Field(alias="audioPath")
    output_dir: Path = Field(alias="outputDir")
    language: str = "zh"
    device: DeviceStrategy = DeviceStrategy.CPU
    preset: str | None = None
    overrides: WorkerDraftOverridesV3 | None = None
    created_at: str | None = Field(default=None, alias="createdAt")


class WorkerDesktopExportsV3(BaseModel):
    """Selected formal outputs for a desktop trusted-lyrics task."""

    model_config = ConfigDict(extra="forbid")

    lrc: bool = True
    swlrc: bool = True
    vocals: bool = False
    accompaniment: bool = False
    alignment_json: bool = Field(default=False, alias="alignmentJson")
    report_json: bool = Field(default=False, alias="reportJson")

    @model_validator(mode="after")
    def require_lyrics_export(self) -> WorkerDesktopExportsV3:
        if not self.lrc and not self.swlrc:
            raise ValueError("At least one of exports.lrc or exports.swlrc must be true.")
        return self


class WorkerDesktopLyricsRequestV3(BaseModel):
    """schemaVersion 3 one-shot desktop trusted-lyrics processing request."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[3] = Field(alias="schemaVersion")
    job_id: str = Field(alias="jobId", min_length=1)
    task_type: Literal[WorkerTaskType.DESKTOP_LYRIC_PROCESSING] = Field(alias="taskType")
    audio_path: Path = Field(alias="audioPath")
    trusted_lyrics_path: Path = Field(alias="trustedLyricsPath")
    output_dir: Path = Field(alias="outputDir")
    language: str = "zh"
    device: DeviceStrategy = DeviceStrategy.CPU
    exports: WorkerDesktopExportsV3 = Field(default_factory=WorkerDesktopExportsV3)
    created_at: str | None = Field(default=None, alias="createdAt")


WorkerRequest = (
    WorkerRequestV1
    | WorkerAlignmentRequestV2
    | WorkerAlignmentRequestV3
    | WorkerDraftExtractionRequestV2
    | WorkerDraftExtractionRequestV3
    | WorkerDesktopLyricsRequestV3
)


@dataclass(frozen=True)
class ClaimedJob:
    """A job directory whose READY marker was atomically claimed."""

    job_dir: Path
    request: WorkerRequest


class WorkerError(Exception):
    """Structured worker failure before or during alignment."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class WorkerCancelled(BaseException):
    """Internal control flow for a requested task cancellation."""


def run_worker(
    *,
    jobs_dir: Path,
    music_dir: Path = Path("/music"),
    poll_interval_seconds: float = 3.0,
    device: DeviceStrategy = DeviceStrategy.CPU,
    once: bool = False,
    min_coverage: float = 0.95,
    estimated_token_review_threshold: int = 0,
    running_timeout_seconds: int = 3600,
) -> None:
    """Poll a shared jobs directory and execute alignment jobs."""

    jobs_root = jobs_dir.resolve(strict=False)
    music_root = music_dir.resolve(strict=False)
    jobs_root.mkdir(parents=True, exist_ok=True)

    active_job: Path | None = None

    def handle_termination(_signum: int, _frame: object) -> None:
        if active_job is not None:
            (active_job / "CANCEL_REQUESTED").touch(exist_ok=True)
        terminate_active_separation()
        raise WorkerCancelled

    previous_handlers = {
        value: signal.signal(value, handle_termination) for value in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        while True:
            mark_abandoned_jobs(jobs_root, timeout_seconds=running_timeout_seconds)
            claimed = claim_next_job(jobs_root)
            if claimed is None:
                if once:
                    return
                time.sleep(poll_interval_seconds)
                continue
            active_job = claimed.job_dir
            try:
                execute_job(
                    claimed,
                    jobs_root=jobs_root,
                    music_root=music_root,
                    device_override=device,
                    min_coverage=min_coverage,
                    estimated_token_review_threshold=estimated_token_review_threshold,
                )
            finally:
                active_job = None
            if once:
                return
    except WorkerCancelled:
        return
    finally:
        for value, handler in previous_handlers.items():
            signal.signal(value, handler)


def claim_next_job(jobs_dir: Path) -> ClaimedJob | None:
    """Claim the first READY job by exclusively creating RUNNING."""

    jobs_root = jobs_dir.resolve(strict=True)
    for job_dir in sorted(jobs_dir.iterdir()):
        if not safe_job_directory(job_dir, jobs_root):
            continue
        ready = job_dir / "READY"
        request_path = job_dir / "request.json"
        if not safe_claim_file(ready, job_dir) or not safe_claim_file(request_path, job_dir):
            continue
        fd: int | None = None
        directory_fd: int | None = None
        try:
            if not safe_job_directory(job_dir, jobs_root):
                continue
            directory_fd = os.open(
                job_dir, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
            )
            fd = os.open(
                "RUNNING", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644, dir_fd=directory_fd
            )
            os.write(fd, f"claimedAt={utc_now()}\n".encode())
        except (FileExistsError, NotADirectoryError, OSError):
            if directory_fd is not None:
                os.close(directory_fd)
            continue
        finally:
            if fd is not None:
                os.close(fd)
        if directory_fd is None:
            continue
        try:
            current = job_dir.stat(follow_symlinks=False)
            opened = os.fstat(directory_fd)
            if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
                os.unlink("RUNNING", dir_fd=directory_fd)
                continue
            os.unlink("READY", dir_fd=directory_fd)
        except FileNotFoundError:
            with suppress(FileNotFoundError):
                os.unlink("RUNNING", dir_fd=directory_fd)
            continue
        finally:
            os.close(directory_fd)
        try:
            request = load_request(job_dir)
        except WorkerError as exc:
            write_failure_status(job_dir, exc.code, exc.message)
            return None
        append_event(
            job_dir,
            WorkerEventType.TASK_ACCEPTED,
            message="Worker accepted the job.",
            details={"requestSchemaVersion": request.schema_version, "taskType": request.task_type},
            flush=True,
        )
        write_running_status(job_dir, request, stage=WorkerStage.VALIDATING_REQUEST)
        return ClaimedJob(job_dir=job_dir, request=request)
    return None


def safe_job_directory(job_dir: Path, jobs_root: Path) -> bool:
    """Reject symlinked/replaced job entries before writing any claim files."""

    try:
        if job_dir.is_symlink() or not job_dir.is_dir():
            return False
        return job_dir.resolve(strict=True).parent == jobs_root
    except OSError:
        return False


def safe_claim_file(path: Path, job_dir: Path) -> bool:
    """Require READY/request.json to be regular, non-symlink files in the job."""

    try:
        if path.is_symlink() or not path.is_file():
            return False
        return path.resolve(strict=True).parent == job_dir.resolve(strict=True)
    except OSError:
        return False


def execute_job(
    claimed: ClaimedJob,
    *,
    jobs_root: Path,
    music_root: Path,
    device_override: DeviceStrategy,
    min_coverage: float,
    estimated_token_review_threshold: int,
) -> None:
    """Run one claimed job and write status.json plus stderr.log."""

    if claimed.request.task_type == WorkerTaskType.LYRIC_DRAFT_EXTRACTION:
        execute_draft_extraction_job(
            claimed,
            jobs_root=jobs_root,
            music_root=music_root,
            device_override=device_override,
        )
        return
    if claimed.request.task_type == WorkerTaskType.DESKTOP_LYRIC_PROCESSING:
        execute_desktop_lyrics_job(
            claimed,
            jobs_root=jobs_root,
            music_root=music_root,
            device_override=device_override,
            min_coverage=min_coverage,
            estimated_token_review_threshold=estimated_token_review_threshold,
        )
        return
    execute_alignment_job(
        claimed,
        jobs_root=jobs_root,
        music_root=music_root,
        device_override=device_override,
        min_coverage=min_coverage,
        estimated_token_review_threshold=estimated_token_review_threshold,
    )


def execute_alignment_job(
    claimed: ClaimedJob,
    *,
    jobs_root: Path,
    music_root: Path,
    device_override: DeviceStrategy,
    min_coverage: float,
    estimated_token_review_threshold: int,
) -> None:
    """Run one claimed alignment job and write status.json plus stderr.log."""

    job_dir = claimed.job_dir
    request = claimed.request
    if request.task_type != WorkerTaskType.LYRICS_ALIGNMENT:
        raise WorkerError("TASK_TYPE_MISMATCH", "Expected a LYRICS_ALIGNMENT request.")
    attempt_id = new_attempt_id()
    attempt_stderr_path = job_dir / "attempts" / f"{attempt_id}.stderr.log"
    stderr_path = job_dir / "stderr.log"
    attempt_stderr_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        validate_request_paths(request, jobs_root=jobs_root, music_root=music_root)
        stage_started(
            job_dir,
            request,
            WorkerStage.ALIGNING,
            attempt_id=attempt_id,
            attempt_stderr_path=attempt_stderr_path,
            device_override=device_override,
        )
        with HeartbeatThread(
            job_dir=job_dir,
            request=request,
            stage=WorkerStage.ALIGNING,
            attempt_id=attempt_id,
            attempt_stderr_path=attempt_stderr_path,
            device_override=device_override,
        ):
            result = align_lyrics(
                audio_path=request.audio_path,
                lyrics_path=request.lyrics_path,
                output_dir=request.output_dir,
                language=request.language,
                device=device_override,
                options=AlignLyricsOptions(
                    section_manifest=request.section_manifest_path,
                    overwrite=True,
                ),
            )
        stage_started(
            job_dir,
            request,
            WorkerStage.EXPORTING_OUTPUTS,
            attempt_id=attempt_id,
            attempt_stderr_path=attempt_stderr_path,
            device_override=device_override,
        )
        validate_result_files(result.files)
        write_attempt_stderr(attempt_stderr_path, stderr_path, "")
        payload = align_json_result_payload(result)
        result_warnings = payload.get("warnings")
        status = classify_result(
            payload,
            min_coverage=min_coverage,
            estimated_token_review_threshold=estimated_token_review_threshold,
        )
        stage_started(
            job_dir,
            request,
            WorkerStage.QUALITY_CHECKING,
            attempt_id=attempt_id,
            attempt_stderr_path=attempt_stderr_path,
            device_override=device_override,
        )
        event_type = (
            WorkerEventType.TASK_NEEDS_REVIEW
            if status == WorkerStatus.NEEDS_REVIEW
            else WorkerEventType.TASK_COMPLETED
        )
        commit_terminal_status(
            job_dir,
            build_status_payload(
                job_dir,
                request=request,
                state=status,
                stage=WorkerStage.FINALIZING,
                attempt_id=attempt_id,
                attempt_stderr_path=attempt_stderr_path,
                device_override=device_override,
                warnings=result_warnings if isinstance(result_warnings, list) else [],
                result=payload,
            ),
            status=status,
            event_type=event_type,
            stage=WorkerStage.FINALIZING,
            message=f"Alignment job finished with state {status}.",
            details={"state": status},
            flush=True,
        )
    except Exception as exc:
        write_attempt_stderr(attempt_stderr_path, stderr_path, traceback.format_exc())
        code = exc.code if isinstance(exc, WorkerError) else align_error_code(exc)
        message = exc.message if isinstance(exc, WorkerError) else alignment_failure_message(exc)
        write_failure_status(
            job_dir,
            code,
            message,
            request=request,
            attempt_id=attempt_id,
            attempt_stderr_path=attempt_stderr_path,
        )


def execute_desktop_lyrics_job(
    claimed: ClaimedJob,
    *,
    jobs_root: Path,
    music_root: Path,
    device_override: DeviceStrategy,
    min_coverage: float,
    estimated_token_review_threshold: int,
) -> None:
    """Run trusted-lyrics alignment and optional two-track export for Desktop."""

    job_dir = claimed.job_dir
    request = claimed.request
    if not isinstance(request, WorkerDesktopLyricsRequestV3):
        raise WorkerError("TASK_TYPE_MISMATCH", "Expected a desktop lyrics request.")
    attempt_id = new_attempt_id()
    attempt_stderr_path = job_dir / "attempts" / f"{attempt_id}.stderr.log"
    stderr_path = job_dir / "stderr.log"
    intermediate_dir = job_dir / "intermediate"
    attempt_stderr_path.parent.mkdir(parents=True, exist_ok=True)
    heartbeat = HeartbeatThread(
        job_dir=job_dir,
        request=request,
        stage=WorkerStage.PREPARING_AUDIO,
        attempt_id=attempt_id,
        attempt_stderr_path=attempt_stderr_path,
        device_override=device_override,
    )

    def start_stage(stage: WorkerStage) -> None:
        raise_if_cancel_requested(job_dir)
        heartbeat.set_stage(stage)
        stage_started(
            job_dir,
            request,
            stage,
            attempt_id=attempt_id,
            attempt_stderr_path=attempt_stderr_path,
            device_override=device_override,
        )

    def alignment_stage_observer(stage: AlignmentPipelineStage) -> None:
        if stage == AlignmentPipelineStage.PREPARING_AUDIO:
            return
        start_stage(WorkerStage(stage.value))

    try:
        raise_if_cancel_requested(job_dir)
        # A previous process may have died before its finally/except cleanup.
        # No Desktop intermediate is part of the formal result contract.
        shutil.rmtree(intermediate_dir, ignore_errors=True)
        validate_request_paths(request, jobs_root=jobs_root, music_root=music_root)
        start_stage(WorkerStage.PREPARING_AUDIO)
        separated = None
        if request.exports.vocals or request.exports.accompaniment:
            start_stage(WorkerStage.SEPARATING_VOCALS)
            with heartbeat:
                separated = separate_vocals_and_accompaniment(
                    request.audio_path,
                    intermediate_dir,
                )
        raise_if_cancel_requested(job_dir)
        if not heartbeat.is_running:
            heartbeat = HeartbeatThread(
                job_dir=job_dir,
                request=request,
                stage=WorkerStage.PREPARING_AUDIO,
                attempt_id=attempt_id,
                attempt_stderr_path=attempt_stderr_path,
                device_override=device_override,
            )
        with heartbeat:
            result = align_lyrics(
                audio_path=request.audio_path,
                lyrics_path=request.trusted_lyrics_path,
                output_dir=request.output_dir,
                language=request.language,
                device=device_override,
                options=AlignLyricsOptions(
                    overwrite=True,
                    stage_observer=alignment_stage_observer,
                ),
            )
        raise_if_cancel_requested(job_dir)
        exported_files = select_desktop_alignment_files(request, result.files)
        if separated is not None:
            exported_files.update(
                export_separated_audio(
                    separated,
                    request.output_dir,
                    export_vocals=request.exports.vocals,
                    export_accompaniment=request.exports.accompaniment,
                )
            )
        remove_unselected_desktop_outputs(request, result.files, request.output_dir)
        artifacts = build_desktop_artifacts(job_dir, exported_files)
        # Formal export is the commit boundary. Cancellation observed after this
        # point must not turn a complete, verified result into an uncontracted
        # partial cancellation; terminal success/review therefore wins.
        stage_started(
            job_dir,
            request,
            WorkerStage.QUALITY_CHECKING,
            attempt_id=attempt_id,
            attempt_stderr_path=attempt_stderr_path,
            device_override=device_override,
        )
        payload = align_json_result_payload(result)
        payload["files"] = {key: str(path) for key, path in exported_files.items()}
        payload.update(artifacts.model_dump(mode="json", by_alias=True))
        result_warnings = payload.get("warnings")
        warnings = result_warnings if isinstance(result_warnings, list) else []
        for warning in warnings:
            append_event(
                job_dir,
                WorkerEventType.WARNING,
                level="WARNING",
                stage=WorkerStage.QUALITY_CHECKING,
                message=str(warning),
                details={"source": "alignment_result"},
            )
        status = classify_result(
            payload,
            min_coverage=min_coverage,
            estimated_token_review_threshold=estimated_token_review_threshold,
        )
        shutil.rmtree(intermediate_dir, ignore_errors=True)
        write_attempt_stderr(attempt_stderr_path, stderr_path, "")
        stage_started(
            job_dir,
            request,
            WorkerStage.FINALIZING,
            attempt_id=attempt_id,
            attempt_stderr_path=attempt_stderr_path,
            device_override=device_override,
        )
        event_type = (
            WorkerEventType.TASK_NEEDS_REVIEW
            if status == WorkerStatus.NEEDS_REVIEW
            else WorkerEventType.TASK_COMPLETED
        )
        commit_terminal_status(
            job_dir,
            build_status_payload(
                job_dir,
                request=request,
                state=status,
                stage=WorkerStage.FINALIZING,
                attempt_id=attempt_id,
                attempt_stderr_path=attempt_stderr_path,
                device_override=device_override,
                warnings=warnings,
                result=payload,
            ),
            status=status,
            event_type=event_type,
            stage=WorkerStage.FINALIZING,
            message=f"Desktop lyrics job finished with state {status}.",
            details={"state": status},
            flush=True,
        )
    except WorkerCancelled:
        shutil.rmtree(intermediate_dir, ignore_errors=True)
        write_attempt_stderr(attempt_stderr_path, stderr_path, "")
        write_cancelled_status(
            job_dir,
            request=request,
            attempt_id=attempt_id,
            attempt_stderr_path=attempt_stderr_path,
            device_override=device_override,
        )
    except Exception as exc:
        shutil.rmtree(intermediate_dir, ignore_errors=True)
        write_attempt_stderr(attempt_stderr_path, stderr_path, traceback.format_exc())
        if isinstance(exc, WorkerError):
            code = exc.code
            message = exc.message
        else:
            code = (
                "VOCAL_SEPARATION_FAILED"
                if isinstance(exc, AudioSeparationError)
                else align_error_code(exc)
            )
            message = str(exc) or "Desktop lyrics processing failed."
        write_failure_status(
            job_dir,
            code,
            message,
            request=request,
            attempt_id=attempt_id,
            attempt_stderr_path=attempt_stderr_path,
        )


def select_desktop_alignment_files(
    request: WorkerDesktopLyricsRequestV3,
    files: dict[str, Path],
) -> dict[str, Path]:
    selected: dict[str, Path] = {}
    flags = {
        "lrc": request.exports.lrc,
        "swlrc": request.exports.swlrc,
        "alignment_json": request.exports.alignment_json,
        "report": request.exports.report_json,
    }
    for key, enabled in flags.items():
        if enabled:
            path = files.get(key)
            if path is None or not path.is_file():
                raise WorkerError("OUTPUT_MISSING", f"Missing selected desktop output: {key}.")
            selected[key] = path
    return selected


def remove_unselected_desktop_outputs(
    request: WorkerDesktopLyricsRequestV3,
    files: dict[str, Path],
    output_root: Path,
) -> None:
    selected = {
        "lrc": request.exports.lrc,
        "swlrc": request.exports.swlrc,
        "alignment_json": request.exports.alignment_json,
        "report": request.exports.report_json,
    }
    try:
        resolved_root = output_root.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise WorkerError("INVALID_OUTPUT_PATH", "Desktop output root is unavailable.") from exc
    for key, path in files.items():
        if key in selected and not selected[key]:
            if path.is_symlink():
                raise WorkerError(
                    "PATH_OUTSIDE_ALLOWED_ROOT", "Refusing to remove a symlink output."
                )
            try:
                resolved = path.resolve(strict=True)
                resolved.relative_to(resolved_root)
            except FileNotFoundError:
                continue
            except (ValueError, OSError) as exc:
                raise WorkerError(
                    "PATH_OUTSIDE_ALLOWED_ROOT",
                    "Pipeline returned an output outside the desktop result directory.",
                ) from exc
            if resolved == resolved_root or not resolved.is_file():
                raise WorkerError(
                    "INVALID_OUTPUT_PATH", "Pipeline returned a non-file output path."
                )
            resolved.unlink()


def build_desktop_artifacts(job_dir: Path, files: dict[str, Path]) -> ResultArtifacts:
    """Build artifacts only after every selected file is verified inside the job."""

    definitions = {
        "lrc": ("lyrics.lrc", ArtifactKind.LRC, "text/plain"),
        "swlrc": ("lyrics.swlrc", ArtifactKind.SWLRC, "text/plain"),
        "alignment_json": ("alignment.json", ArtifactKind.ALIGNMENT_JSON, "application/json"),
        "report": ("report.json", ArtifactKind.REPORT_JSON, "application/json"),
        "vocals": ("audio.vocals", ArtifactKind.VOCALS, "audio/wav"),
        "accompaniment": ("audio.accompaniment", ArtifactKind.ACCOMPANIMENT, "audio/wav"),
    }
    artifacts: list[ResultArtifact] = []
    for key, path in files.items():
        if not path.is_file():
            raise WorkerError("OUTPUT_MISSING", f"Artifact does not exist: {path.name}.")
        try:
            relative = path.resolve(strict=True).relative_to(job_dir.resolve(strict=True))
        except ValueError as exc:
            raise WorkerError(
                "PATH_OUTSIDE_ALLOWED_ROOT", "Artifact escaped the job directory."
            ) from exc
        artifact_id, kind, media_type = definitions[key]
        artifacts.append(
            ResultArtifact(
                id=artifact_id,
                kind=kind,
                relativePath=relative.as_posix(),
                mediaType=media_type,
            )
        )
    return ResultArtifacts(artifacts=artifacts)


def execute_draft_extraction_job(
    claimed: ClaimedJob,
    *,
    jobs_root: Path,
    music_root: Path,
    device_override: DeviceStrategy,
    service: CandidateLyricsExtractionService | None = None,
) -> None:
    """Run one claimed candidate lyric draft extraction job."""

    job_dir = claimed.job_dir
    request = claimed.request
    if not isinstance(request, WorkerDraftExtractionRequestV2 | WorkerDraftExtractionRequestV3):
        raise WorkerError("TASK_TYPE_MISMATCH", "Expected a LYRIC_DRAFT_EXTRACTION request.")
    attempt_id = new_attempt_id()
    attempt_stderr_path = job_dir / "attempts" / f"{attempt_id}.stderr.log"
    stderr_path = job_dir / "stderr.log"
    attempt_stderr_path.parent.mkdir(parents=True, exist_ok=True)
    intermediate_dir = job_dir / "intermediate"
    try:
        validate_request_paths(request, jobs_root=jobs_root, music_root=music_root)
        config = resolve_worker_draft_config(request)
        first_stage = (
            WorkerStage.TRANSCRIBING if config.skip_separation else WorkerStage.SEPARATING_VOCALS
        )
        stage_started(
            job_dir,
            request,
            first_stage,
            attempt_id=attempt_id,
            attempt_stderr_path=attempt_stderr_path,
            device_override=device_override,
            details={
                "model": config.asr_model,
                "skipSeparation": config.skip_separation,
                "vadFilter": config.vad_filter,
            },
        )
        extraction_service = service or CandidateLyricsExtractionService()
        with HeartbeatThread(
            job_dir=job_dir,
            request=request,
            stage=first_stage,
            attempt_id=attempt_id,
            attempt_stderr_path=attempt_stderr_path,
            device_override=device_override,
        ):
            result = extraction_service.extract(
                CandidateLyricsExtractionRequest(
                    audio_path=request.audio_path,
                    output_dir=request.output_dir,
                    language=request.language,
                    model=config.asr_model,
                    device=device_override.value,
                    skip_separation=config.skip_separation,
                    vad_filter=config.vad_filter,
                    condition_on_previous_text=config.condition_on_previous_text,
                    keep_suspected_metadata=config.keep_suspected_metadata,
                    retain_intermediate=config.retain_intermediate,
                    intermediate_dir=intermediate_dir,
                    task_type=request.task_type,
                    requested_config=worker_requested_config(request),
                    resolved_config=config,
                )
            )
        stage_started(
            job_dir,
            request,
            WorkerStage.WRITING_OUTPUTS,
            attempt_id=attempt_id,
            attempt_stderr_path=attempt_stderr_path,
            device_override=device_override,
        )
        validate_draft_result_files(result.files)
        if not config.retain_intermediate:
            shutil.rmtree(intermediate_dir, ignore_errors=True)
        write_attempt_stderr(attempt_stderr_path, stderr_path, "")
        report_warnings = result.report.get("warnings", [])
        warning_count = len(report_warnings) if isinstance(report_warnings, list) else 0
        commit_terminal_status(
            job_dir,
            build_status_payload(
                job_dir,
                request=request,
                state=WorkerStatus.SUCCEEDED,
                stage=WorkerStage.FINALIZING,
                attempt_id=attempt_id,
                attempt_stderr_path=attempt_stderr_path,
                device_override=device_override,
                warnings=report_warnings if isinstance(report_warnings, list) else [],
                result={
                    "success": True,
                    "taskType": request.task_type,
                    "files": result.files,
                    "report": result.report,
                },
            ),
            status=WorkerStatus.SUCCEEDED,
            event_type=WorkerEventType.TASK_COMPLETED,
            stage=WorkerStage.FINALIZING,
            message="Draft extraction job completed.",
            details={"warningCount": warning_count},
            flush=True,
        )
    except Exception as exc:
        try:
            config = resolve_worker_draft_config(request)
            if not config.retain_intermediate:
                shutil.rmtree(intermediate_dir, ignore_errors=True)
        except DraftConfigError:
            shutil.rmtree(intermediate_dir, ignore_errors=True)
        write_attempt_stderr(attempt_stderr_path, stderr_path, traceback.format_exc())
        code = exc.code if isinstance(exc, WorkerError) else "ASR_TRANSCRIPTION_FAILED"
        message = exc.message if isinstance(exc, WorkerError) else str(exc)
        write_failure_status(
            job_dir,
            code,
            message,
            request=request,
            attempt_id=attempt_id,
            attempt_stderr_path=attempt_stderr_path,
        )


def load_request(job_dir: Path) -> WorkerRequest:
    """Load and validate request.json."""

    request_path = job_dir / "request.json"
    try:
        data = json.loads(request_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise WorkerError("REQUEST_MISSING", f"Missing request.json: {request_path}") from exc
    except json.JSONDecodeError as exc:
        raise WorkerError("REQUEST_INVALID_JSON", f"Invalid request.json: {exc}") from exc
    if not isinstance(data, dict):
        raise WorkerError("REQUEST_INVALID", "request.json must contain a JSON object.")
    schema_version = data.get("schemaVersion")
    try:
        if schema_version == 1:
            request: WorkerRequest = WorkerRequestV1.model_validate(data)
        elif schema_version == 2:
            task_type = data.get("taskType")
            if task_type == WorkerTaskType.LYRICS_ALIGNMENT:
                request = WorkerAlignmentRequestV2.model_validate(data)
            elif task_type == WorkerTaskType.LYRIC_DRAFT_EXTRACTION:
                request = WorkerDraftExtractionRequestV2.model_validate(data)
            elif task_type is None:
                raise WorkerError("TASK_TYPE_MISSING", "schemaVersion 2 requires taskType.")
            else:
                raise WorkerError("UNKNOWN_TASK_TYPE", f"Unsupported taskType: {task_type!r}.")
        elif schema_version == 3:
            task_type = data.get("taskType")
            if task_type == WorkerTaskType.LYRICS_ALIGNMENT:
                request = WorkerAlignmentRequestV3.model_validate(data)
            elif task_type == WorkerTaskType.LYRIC_DRAFT_EXTRACTION:
                request = WorkerDraftExtractionRequestV3.model_validate(data)
                resolve_worker_draft_config(request)
            elif task_type == WorkerTaskType.DESKTOP_LYRIC_PROCESSING:
                request = WorkerDesktopLyricsRequestV3.model_validate(data)
            elif task_type is None:
                raise WorkerError("TASK_TYPE_MISSING", "schemaVersion 3 requires taskType.")
            else:
                raise WorkerError("UNKNOWN_TASK_TYPE", f"Unsupported taskType: {task_type!r}.")
        else:
            raise WorkerError(
                "UNSUPPORTED_SCHEMA",
                "Only worker schemaVersion 1, 2, and 3 are supported.",
            )
    except ValidationError as exc:
        raise WorkerError("REQUEST_INVALID", str(exc)) from exc
    except DraftConfigError as exc:
        raise WorkerError(exc.code, exc.message) from exc
    if request.job_id != job_dir.name:
        raise WorkerError(
            "JOB_ID_MISMATCH",
            f"request jobId {request.job_id!r} does not match directory {job_dir.name!r}.",
        )
    return request


def validate_request_paths(
    request: WorkerRequest,
    *,
    jobs_root: Path,
    music_root: Path,
) -> None:
    """Restrict request paths to mounted /music and /jobs trees."""

    job_dir = jobs_root / request.job_id
    require_existing_file_inside(request.audio_path, music_root, field="audioPath")
    require_inside(request.output_dir, jobs_root, field="outputDir")
    require_exact_output_dir(request.output_dir, job_dir)
    if request.task_type == WorkerTaskType.LYRICS_ALIGNMENT:
        if not isinstance(
            request,
            WorkerRequestV1 | WorkerAlignmentRequestV2 | WorkerAlignmentRequestV3,
        ):
            raise WorkerError("TASK_TYPE_MISMATCH", "Invalid alignment request model.")
        require_existing_file_inside(request.lyrics_path, job_dir, field="lyricsPath")
        if request.section_manifest_path is not None:
            require_existing_file_inside(
                request.section_manifest_path,
                job_dir,
                field="sectionManifestPath",
            )
    elif request.task_type == WorkerTaskType.DESKTOP_LYRIC_PROCESSING:
        if not isinstance(request, WorkerDesktopLyricsRequestV3):
            raise WorkerError("TASK_TYPE_MISMATCH", "Invalid desktop lyrics request model.")
        require_existing_file_inside(
            request.trusted_lyrics_path,
            job_dir,
            field="trustedLyricsPath",
        )


def resolve_worker_draft_config(
    request: WorkerDraftExtractionRequestV2 | WorkerDraftExtractionRequestV3,
) -> DraftExtractionConfig:
    """Resolve draft extraction config for Worker request schema versions."""

    if isinstance(request, WorkerDraftExtractionRequestV3):
        overrides = (
            request.overrides.to_resolver_overrides() if request.overrides is not None else None
        )
        return resolve_draft_extraction_config(
            preset=request.preset,
            overrides=overrides,
        )
    return resolve_draft_extraction_config(
        asr_model=request.asr_model,
        skip_separation=request.skip_separation,
        vad_filter=request.vad_filter,
        condition_on_previous_text=request.condition_on_previous_text,
        keep_suspected_metadata=request.keep_suspected_metadata,
        retain_intermediate=request.retain_intermediate,
    )


def worker_requested_config(request: WorkerRequest) -> dict[str, object]:
    """Return request-supplied task configuration for status snapshots."""

    if isinstance(request, WorkerDraftExtractionRequestV3):
        overrides = (
            request.overrides.to_resolver_overrides() if request.overrides is not None else None
        )
        return requested_draft_config_json(
            preset=request.preset,
            overrides=overrides,
        )
    if isinstance(request, WorkerDraftExtractionRequestV2):
        return requested_draft_config_json(
            preset=None,
            legacy_fields={
                "asrModel": request.asr_model,
                "skipSeparation": request.skip_separation,
                "vadFilter": request.vad_filter,
                "conditionOnPreviousText": request.condition_on_previous_text,
                "keepSuspectedMetadata": request.keep_suspected_metadata,
                "retainIntermediate": request.retain_intermediate,
            },
        )
    if isinstance(request, WorkerDesktopLyricsRequestV3):
        return {
            "language": request.language,
            "device": str(request.device),
            "exports": request.exports.model_dump(mode="json", by_alias=True),
        }
    return {
        "language": request.language,
        "device": str(request.device),
        "sectionManifestPath": str(request.section_manifest_path)
        if request.section_manifest_path is not None
        else None,
    }


def worker_resolved_config(
    request: WorkerRequest,
    *,
    device_override: DeviceStrategy | None = None,
) -> dict[str, object]:
    """Return final execution configuration after Worker runtime constraints."""

    if isinstance(request, WorkerDraftExtractionRequestV2 | WorkerDraftExtractionRequestV3):
        config = resolve_worker_draft_config(request)
        payload = config.to_worker_json()
        payload["device"] = str(device_override or request.device)
        payload["language"] = request.language
        return payload
    if isinstance(request, WorkerDesktopLyricsRequestV3):
        return {
            "language": request.language,
            "device": str(device_override or request.device),
            "exports": request.exports.model_dump(mode="json", by_alias=True),
        }
    return {
        "language": request.language,
        "device": str(device_override or request.device),
        "sectionManifestPath": str(request.section_manifest_path)
        if request.section_manifest_path is not None
        else None,
    }


def require_inside(path: Path, root: Path, *, field: str) -> None:
    """Reject relative paths and resolved paths outside a configured root."""

    if not path.is_absolute():
        raise WorkerError("PATH_NOT_ABSOLUTE", f"{field} must be an absolute path: {path}")
    resolved_path = path.resolve(strict=False)
    resolved_root = root.resolve(strict=False)
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise WorkerError(
            "PATH_OUTSIDE_ALLOWED_ROOT",
            f"{field} must stay under {resolved_root}: {path}",
        ) from exc


def require_existing_file_inside(path: Path, root: Path, *, field: str) -> None:
    """Reject missing files, symlink escapes, relative paths, and paths outside root."""

    require_inside(path, root, field=field)
    if not path.exists():
        raise WorkerError("PATH_MISSING", f"{field} does not exist.")
    if not path.is_file():
        raise WorkerError("PATH_NOT_FILE", f"{field} is not a file.")
    require_inside(path.resolve(strict=True), root.resolve(strict=False), field=field)


def require_exact_output_dir(output_dir: Path, job_dir: Path) -> None:
    """Require outputDir to be exactly the current job's result directory."""

    if not output_dir.is_absolute():
        raise WorkerError("PATH_NOT_ABSOLUTE", "outputDir must be an absolute path.")
    expected = (job_dir / "result").resolve(strict=False)
    resolved = output_dir.resolve(strict=False)
    if resolved != expected:
        raise WorkerError(
            "OUTPUT_DIR_INVALID",
            "outputDir must be the current job result directory.",
        )
    if output_dir.exists() and output_dir.is_symlink():
        raise WorkerError("PATH_OUTSIDE_ALLOWED_ROOT", "outputDir must not be a symlink.")
    parent = output_dir.parent
    if parent.exists():
        require_inside(
            parent.resolve(strict=True),
            job_dir.resolve(strict=False),
            field="outputDir",
        )


def classify_result(
    payload: dict[str, object],
    *,
    min_coverage: float,
    estimated_token_review_threshold: int,
) -> WorkerStatus:
    """Map a successful align JSON result to SUCCEEDED or NEEDS_REVIEW."""

    summary = payload.get("summary")
    warnings = payload.get("warnings")
    if not isinstance(summary, dict):
        return WorkerStatus.NEEDS_REVIEW
    skipped = summary.get("skipped_line_count", 0)
    coverage = summary.get("coverage", 0.0)
    estimated = summary.get("estimated_token_count", 0)
    if warnings:
        return WorkerStatus.NEEDS_REVIEW
    if isinstance(skipped, int) and skipped > 0:
        return WorkerStatus.NEEDS_REVIEW
    if isinstance(coverage, int | float) and coverage < min_coverage:
        return WorkerStatus.NEEDS_REVIEW
    if isinstance(estimated, int) and estimated > estimated_token_review_threshold:
        return WorkerStatus.NEEDS_REVIEW
    return WorkerStatus.SUCCEEDED


def validate_result_files(files: dict[str, Path]) -> None:
    """Ensure official output files exist before declaring success."""

    required = {
        "alignment_json": "alignment.json",
        "lrc": "lyrics.lrc",
        "swlrc": "lyrics.swlrc",
        "report": "report.json",
    }
    missing: list[str] = []
    for key, filename in required.items():
        path = files.get(key)
        if path is None:
            missing.append(f"{key}:missing_from_result")
            continue
        if path.name != filename or not path.exists() or not path.is_file():
            missing.append(str(path))
    if missing:
        raise WorkerError(
            "OUTPUT_MISSING",
            "Alignment completed but required output files are missing: " + ", ".join(missing),
        )


def validate_draft_result_files(files: dict[str, Path]) -> None:
    """Ensure candidate draft output files exist before declaring success."""

    required = {
        "transcript_raw": "transcript.raw.txt",
        "transcript_segments": "transcript.segments.json",
        "transcript_cleaned": "transcript.cleaned.txt",
        "report": "report.json",
    }
    missing: list[str] = []
    for key, filename in required.items():
        path = files.get(key)
        if path is None:
            missing.append(f"{key}:missing_from_result")
            continue
        if path.name != filename or not path.exists() or not path.is_file():
            missing.append(filename)
    if missing:
        raise WorkerError(
            "OUTPUT_MISSING",
            "Candidate extraction completed but required output files are missing: "
            + ", ".join(missing),
        )


def mark_abandoned_jobs(jobs_dir: Path, *, timeout_seconds: int) -> None:
    """Mark stale RUNNING jobs as ABANDONED using heartbeat before marker mtime."""

    now = time.time()
    for running in jobs_dir.glob("*/RUNNING"):
        job_dir = running.parent
        status = read_status_snapshot(job_dir)
        heartbeat_at = status.get("heartbeatAt")
        heartbeat_age = heartbeat_age_seconds(heartbeat_at)
        age = heartbeat_age if heartbeat_age is not None else now - running.stat().st_mtime
        if age < timeout_seconds:
            continue
        abandoned = job_dir / "ABANDONED"
        (job_dir / "READY").unlink(missing_ok=True)
        os.replace(running, abandoned)
        job_id = job_dir.name
        identity = read_abandoned_job_identity(job_dir)
        message = f"Worker heartbeat exceeded {timeout_seconds} seconds."
        commit_terminal_status(
            job_dir,
            build_status_payload(
                job_dir,
                request=None,
                state=WorkerStatus.ABANDONED,
                stage=WorkerStage.FINALIZING,
                error=worker_error_payload(
                    "RUNNING_TIMEOUT",
                    message,
                    stderr_path=job_dir / "stderr.log",
                ),
            )
            | {
                "schemaVersion": identity["schemaVersion"],
                "requestSchemaVersion": identity["schemaVersion"],
                "jobId": identity["jobId"] or job_id,
                "taskType": identity["taskType"],
            },
            status=WorkerStatus.ABANDONED,
            event_type=WorkerEventType.TASK_ABANDONED,
            level="WARNING",
            stage=WorkerStage.FINALIZING,
            message=message,
            details={"timeoutSeconds": timeout_seconds, "ageSeconds": age},
            flush=True,
        )


def heartbeat_age_seconds(value: object) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0.0, (datetime.now(UTC) - parsed).total_seconds())


def read_abandoned_job_identity(job_dir: Path) -> dict[str, object]:
    """Best-effort schema/task metadata for stale RUNNING jobs."""

    fallback: dict[str, object] = {
        "schemaVersion": None,
        "jobId": job_dir.name,
        "taskType": None,
    }
    for filename in ("status.json", "request.json"):
        path = job_dir / filename
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        schema_version = data.get("schemaVersion", fallback["schemaVersion"])
        job_id = data.get("jobId", fallback["jobId"])
        task_type = data.get("taskType", fallback["taskType"])
        return {
            "schemaVersion": schema_version,
            "jobId": job_id if isinstance(job_id, str) else fallback["jobId"],
            "taskType": task_type,
        }
    return fallback


def write_failure_status(
    job_dir: Path,
    code: str,
    message: str,
    *,
    request: WorkerRequest | None = None,
    attempt_id: str | None = None,
    attempt_stderr_path: Path | None = None,
) -> None:
    """Write a stable FAILED status.json."""

    error = worker_error_payload(
        code,
        message,
        stderr_path=job_dir / "stderr.log",
        attempt_stderr_path=attempt_stderr_path,
    )
    payload: dict[str, Any] = build_status_payload(
        job_dir,
        request=request,
        state=WorkerStatus.FAILED,
        stage=WorkerStage.FINALIZING,
        attempt_id=attempt_id,
        attempt_stderr_path=attempt_stderr_path,
        error=error,
    )
    commit_terminal_status(
        job_dir,
        payload,
        status=WorkerStatus.FAILED,
        event_type=WorkerEventType.TASK_FAILED,
        level="ERROR",
        message=message,
        details={"code": code, "stderrPath": error["stderrPath"]},
        flush=True,
    )


def raise_if_cancel_requested(job_dir: Path) -> None:
    """Stop at a safe stage boundary when the caller requested cancellation."""

    if (job_dir / "CANCEL_REQUESTED").exists():
        raise WorkerCancelled


def write_cancelled_status(
    job_dir: Path,
    *,
    request: WorkerRequest,
    attempt_id: str,
    attempt_stderr_path: Path,
    device_override: DeviceStrategy,
) -> None:
    """Write cancellation as its own terminal outcome, never as a failure."""

    commit_terminal_status(
        job_dir,
        build_status_payload(
            job_dir,
            request=request,
            state=WorkerStatus.CANCELLED,
            stage=WorkerStage.FINALIZING,
            attempt_id=attempt_id,
            attempt_stderr_path=attempt_stderr_path,
            device_override=device_override,
        ),
        status=WorkerStatus.CANCELLED,
        event_type=WorkerEventType.TASK_CANCELLED,
        stage=WorkerStage.FINALIZING,
        message="Task cancellation completed.",
        flush=True,
    )


def write_running_status(
    job_dir: Path,
    request: WorkerRequest,
    *,
    stage: str | WorkerStage | None,
    attempt_id: str | None = None,
    attempt_stderr_path: Path | None = None,
    device_override: DeviceStrategy | None = None,
) -> None:
    """Write a RUNNING status payload using v0.5.0 snapshot semantics."""

    write_status(
        job_dir,
        build_status_payload(
            job_dir,
            request=request,
            state=WorkerStatus.RUNNING,
            stage=stage,
            attempt_id=attempt_id,
            attempt_stderr_path=attempt_stderr_path,
            device_override=device_override,
        ),
    )


def stage_started(
    job_dir: Path,
    request: WorkerRequest,
    stage: WorkerStage,
    *,
    attempt_id: str,
    attempt_stderr_path: Path,
    device_override: DeviceStrategy,
    details: dict[str, object] | None = None,
) -> None:
    write_running_status(
        job_dir,
        request,
        stage=stage,
        attempt_id=attempt_id,
        attempt_stderr_path=attempt_stderr_path,
        device_override=device_override,
    )
    append_event(
        job_dir,
        WorkerEventType.STAGE_STARTED,
        stage=stage,
        message=f"Started stage {stage}.",
        details=details,
    )


def build_status_payload(
    job_dir: Path,
    *,
    request: WorkerRequest | None,
    state: WorkerStatus,
    stage: str | WorkerStage | None,
    attempt_id: str | None = None,
    attempt_stderr_path: Path | None = None,
    device_override: DeviceStrategy | None = None,
    warnings: list[object] | None = None,
    error: dict[str, object] | None = None,
    result: dict[str, object] | None = None,
) -> dict[str, Any]:
    """Build status.json while preserving attempt and stage timestamps."""

    now = utc_now()
    previous = read_status_snapshot(job_dir)
    stage_value = str(stage) if stage is not None else None
    previous_stage = previous.get("stage")
    started_at = previous.get("startedAt") if isinstance(previous.get("startedAt"), str) else now
    stage_started_at = (
        previous.get("stageStartedAt")
        if previous_stage == stage_value and isinstance(previous.get("stageStartedAt"), str)
        else now
    )
    previous_heartbeat = previous.get("heartbeatAt")
    heartbeat_at = (
        now
        if state == WorkerStatus.RUNNING or not isinstance(previous_heartbeat, str)
        else previous_heartbeat
    )
    request_schema_version = request.schema_version if request is not None else None
    task_type = request.task_type if request is not None else None
    payload: dict[str, Any] = {
        "statusSchemaVersion": 1,
        "requestSchemaVersion": request_schema_version,
        "schemaVersion": request_schema_version,
        "jobId": request.job_id if request is not None else job_dir.name,
        "taskType": task_type,
        "status": state,
        "state": state,
        "stage": stage_value,
        "startedAt": started_at,
        "stageStartedAt": stage_started_at,
        "updatedAt": now,
        "heartbeatAt": heartbeat_at,
        "progress": complete_progress() if state in TERMINAL_STATUSES else indeterminate_progress(),
        "attempt": None,
        "requestedConfig": worker_requested_config(request) if request is not None else {},
        "resolvedConfig": worker_resolved_config(request, device_override=device_override)
        if request is not None
        else {},
        "warnings": warnings or [],
        "warningCount": len(warnings or []),
        "errorMessage": error["message"] if error is not None else None,
        "error": error,
        "result": result,
    }
    if request is not None and request.schema_version == 3:
        payload["runtime"] = runtime_metadata()
    if attempt_id is not None:
        payload["attempt"] = {
            "id": attempt_id,
            "number": attempt_number(job_dir, attempt_id),
            "stderrPath": relative_job_path(job_dir, attempt_stderr_path)
            if attempt_stderr_path is not None
            else None,
            "stderr": str(attempt_stderr_path) if attempt_stderr_path is not None else None,
        }
    return payload


TERMINAL_STATUSES = {
    WorkerStatus.SUCCEEDED,
    WorkerStatus.NEEDS_REVIEW,
    WorkerStatus.FAILED,
    WorkerStatus.ABANDONED,
    WorkerStatus.CANCELLED,
}


def runtime_metadata() -> dict[str, str]:
    """Return truthful runtime identity for schema v3 status snapshots."""

    return {
        "workerVersion": __version__,
        "pythonVersion": platform.python_version(),
        "platform": f"{platform.system()}-{platform.machine()}",
    }


def indeterminate_progress() -> dict[str, object]:
    return {"kind": "INDETERMINATE", "current": None, "total": None, "fraction": None}


def complete_progress() -> dict[str, object]:
    return {"kind": "COMPLETE", "current": 1, "total": 1, "fraction": 1.0}


def read_status_snapshot(job_dir: Path) -> dict[str, Any]:
    try:
        data = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def worker_error_payload(
    code: str,
    message: str,
    *,
    stderr_path: Path,
    attempt_stderr_path: Path | None = None,
) -> dict[str, object]:
    """Return structured failure data without exposing tracebacks as the message."""

    return {
        "code": code,
        "message": sanitize_error_message(code, message),
        "retryable": code in {"MODEL_DOWNLOAD_FAILED", "MODEL_NOT_AVAILABLE", "RUNNING_TIMEOUT"},
        "suggestedAction": suggested_action(code),
        "stderrPath": relative_job_path(stderr_path.parent, stderr_path),
        "stderr": str(stderr_path),
        "attemptStderrPath": relative_job_path(
            attempt_stderr_path.parent.parent,
            attempt_stderr_path,
        )
        if attempt_stderr_path is not None
        else None,
    }


def sanitize_error_message(code: str, message: str) -> str:
    if "Traceback (most recent call last)" in message:
        return f"{code} occurred. Inspect stderr for details."
    return message.splitlines()[0] if message else f"{code} occurred."


def alignment_failure_message(exc: Exception) -> str:
    """Return a useful status message while leaving the traceback in stderr."""
    message = str(exc).strip()
    if "punkt_tab" in message:
        return (
            "Alignment failed because the required NLTK punkt_tab resource is unavailable. "
            "See stderr for details."
        )
    if message:
        return message
    return "Alignment failed because a required resource is unavailable. See stderr for details."


def suggested_action(code: str) -> str:
    if code in {"REQUEST_INVALID", "REQUEST_INVALID_JSON", "INVALID_PRESET"}:
        return "Fix request.json and create a new job."
    if code.startswith("PATH_") or code == "OUTPUT_DIR_INVALID":
        return "Check mounted paths and job directory layout."
    if code in {"ASR_TRANSCRIPTION_FAILED", "CANDIDATE_EXTRACTION_FAILED"}:
        return "Inspect the source audio or try a different extraction preset."
    if code in {"ALIGNMENT_FAILED", "QUALITY_CHECK_FAILED"}:
        return "Inspect trusted lyrics, audio, and attempt stderr."
    if code == "RUNNING_TIMEOUT":
        return "Check whether the previous Worker process is still alive before retrying."
    return "Inspect attempt stderr for details."


def attempt_number(job_dir: Path, attempt_id: str) -> int:
    attempts_dir = job_dir / "attempts"
    existing = sorted(path.name for path in attempts_dir.glob("*.stderr.log"))
    name = f"{attempt_id}.stderr.log"
    if name in existing:
        return existing.index(name) + 1
    return len(existing) + 1


def relative_job_path(base_dir: Path, path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return str(path.relative_to(base_dir))
    except ValueError:
        return str(path)


def append_event(
    job_dir: Path,
    event_type: WorkerEventType,
    *,
    level: str = "INFO",
    stage: str | WorkerStage | None = None,
    message: str,
    details: dict[str, object] | None = None,
    flush: bool = False,
) -> None:
    """Append one independently parseable JSON event."""

    events_path = job_dir / "events.jsonl"
    timestamp = utc_now()
    payload = {
        "eventId": new_event_id(job_dir, timestamp),
        "timestamp": timestamp,
        "level": level,
        "type": event_type,
        "stage": str(stage) if stage is not None else None,
        "message": message,
        "details": details or {},
    }
    with events_path.open("a", encoding="utf-8") as event_file:
        event_file.write(json.dumps(normalize_status(payload), ensure_ascii=False) + "\n")
        if flush:
            event_file.flush()
            os.fsync(event_file.fileno())


def new_event_id(job_dir: Path, timestamp: str) -> str:
    count = 1
    events_path = job_dir / "events.jsonl"
    try:
        with events_path.open("r", encoding="utf-8") as event_file:
            for line in event_file:
                if not line.strip():
                    continue
                try:
                    json.loads(line)
                except json.JSONDecodeError:
                    continue
                count += 1
    except FileNotFoundError:
        pass
    compact = timestamp.replace("-", "").replace(":", "")
    return f"{compact}-{count:04d}"


def read_events_jsonl(events_path: Path) -> list[dict[str, object]]:
    """Read events while tolerating an incomplete final line."""

    events: list[dict[str, object]] = []
    for line in events_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            events.append(parsed)
    return events


class HeartbeatThread:
    """Periodic status heartbeat for long blocking task calls."""

    def __init__(
        self,
        *,
        job_dir: Path,
        request: WorkerRequest,
        stage: WorkerStage,
        attempt_id: str,
        attempt_stderr_path: Path,
        device_override: DeviceStrategy,
        interval_seconds: float = 30.0,
    ) -> None:
        self.job_dir = job_dir
        self.request = request
        self.stage = stage
        self.attempt_id = attempt_id
        self.attempt_stderr_path = attempt_stderr_path
        self.device_override = device_override
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._started = False

    def __enter__(self) -> HeartbeatThread:
        self._started = True
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        self._thread.join(timeout=1.0)

    @property
    def is_running(self) -> bool:
        return self._started and self._thread.is_alive()

    def set_stage(self, stage: WorkerStage) -> None:
        """Keep heartbeat snapshots aligned with the latest observed stage."""

        self.stage = stage

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            write_running_status(
                self.job_dir,
                self.request,
                stage=self.stage,
                attempt_id=self.attempt_id,
                attempt_stderr_path=self.attempt_stderr_path,
                device_override=self.device_override,
            )


def write_terminal_marker(job_dir: Path, status: WorkerStatus) -> None:
    """Write terminal marker files without removing RUNNING claim evidence."""

    if status not in {
        WorkerStatus.SUCCEEDED,
        WorkerStatus.NEEDS_REVIEW,
        WorkerStatus.FAILED,
        WorkerStatus.ABANDONED,
        WorkerStatus.CANCELLED,
    }:
        return
    terminal_statuses = {
        WorkerStatus.SUCCEEDED,
        WorkerStatus.NEEDS_REVIEW,
        WorkerStatus.FAILED,
        WorkerStatus.ABANDONED,
        WorkerStatus.CANCELLED,
    }
    for other in terminal_statuses - {status}:
        (job_dir / other.value).unlink(missing_ok=True)
    marker = job_dir / status.value
    temporary = job_dir / f".{status.value}.{os.getpid()}.{time.time_ns()}.tmp"
    temporary.write_text(f"{status.value} at {utc_now()}\n", encoding="utf-8")
    os.replace(temporary, marker)


def commit_terminal_status(
    job_dir: Path,
    payload: dict[str, Any],
    *,
    status: WorkerStatus,
    event_type: WorkerEventType,
    **event: Any,
) -> None:
    """Commit status first; diagnostic/marker failures cannot reclassify the task."""

    write_status(job_dir, payload)
    with suppress(Exception):
        append_event(job_dir, event_type, **event)
    with suppress(Exception):
        write_terminal_marker(job_dir, status)


def write_status(job_dir: Path, payload: dict[str, Any]) -> None:
    """Atomically replace status.json."""

    status_path = job_dir / "status.json"
    tmp_path = job_dir / f".status.json.{os.getpid()}.{time.time_ns()}.tmp"
    serializable = normalize_status(payload)
    with tmp_path.open("w", encoding="utf-8") as tmp_file:
        tmp_file.write(json.dumps(serializable, ensure_ascii=False, indent=2) + "\n")
        tmp_file.flush()
        os.fsync(tmp_file.fileno())
    os.replace(tmp_path, status_path)


def normalize_status(value: Any) -> Any:
    """Convert enums and paths before JSON serialization."""

    if isinstance(value, StrEnum):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: normalize_status(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize_status(item) for item in value]
    return value


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp."""

    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_attempt_id() -> str:
    """Return a filesystem-safe attempt identifier."""

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{os.getpid()}-{time.time_ns()}"


def write_attempt_stderr(attempt_path: Path, latest_path: Path, content: str) -> None:
    """Preserve per-attempt stderr while updating the latest stderr.log."""

    attempt_path.write_text(content, encoding="utf-8")
    latest_tmp_path = latest_path.with_name(f".stderr.log.{os.getpid()}.{time.time_ns()}.tmp")
    latest_tmp_path.write_text(content, encoding="utf-8")
    os.replace(latest_tmp_path, latest_path)
