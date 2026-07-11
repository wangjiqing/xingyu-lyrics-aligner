"""Shared-directory worker for Docker Compose integrations."""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
import traceback
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from xingyu_lyrics_aligner.api import AlignLyricsOptions, align_lyrics
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


class WorkerStatus(StrEnum):
    """Stable status values written to status.json."""

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    FAILED = "FAILED"
    ABANDONED = "ABANDONED"


class WorkerTaskType(StrEnum):
    """Worker task types supported by schemaVersion 2."""

    LYRICS_ALIGNMENT = "LYRICS_ALIGNMENT"
    LYRIC_DRAFT_EXTRACTION = "LYRIC_DRAFT_EXTRACTION"


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


WorkerRequest = (
    WorkerRequestV1
    | WorkerAlignmentRequestV2
    | WorkerAlignmentRequestV3
    | WorkerDraftExtractionRequestV2
    | WorkerDraftExtractionRequestV3
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

    while True:
        mark_abandoned_jobs(jobs_root, timeout_seconds=running_timeout_seconds)
        claimed = claim_next_job(jobs_root)
        if claimed is None:
            if once:
                return
            time.sleep(poll_interval_seconds)
            continue
        execute_job(
            claimed,
            jobs_root=jobs_root,
            music_root=music_root,
            device_override=device,
            min_coverage=min_coverage,
            estimated_token_review_threshold=estimated_token_review_threshold,
        )
        if once:
            return


def claim_next_job(jobs_dir: Path) -> ClaimedJob | None:
    """Claim the first READY job by exclusively creating RUNNING."""

    for job_dir in sorted(path for path in jobs_dir.iterdir() if path.is_dir()):
        ready = job_dir / "READY"
        running = job_dir / "RUNNING"
        if not ready.exists():
            continue
        fd: int | None = None
        try:
            fd = os.open(running, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            os.write(fd, f"claimedAt={utc_now()}\n".encode())
        except FileExistsError:
            continue
        finally:
            if fd is not None:
                os.close(fd)
        try:
            ready.unlink()
        except FileNotFoundError:
            running.unlink(missing_ok=True)
            continue
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
        write_terminal_marker(job_dir, status)
        event_type = (
            WorkerEventType.TASK_NEEDS_REVIEW
            if status == WorkerStatus.NEEDS_REVIEW
            else WorkerEventType.TASK_COMPLETED
        )
        write_status(
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
        )
        append_event(
            job_dir,
            event_type,
            stage=WorkerStage.FINALIZING,
            message=f"Alignment job finished with state {status}.",
            details={"state": status},
            flush=True,
        )
    except Exception as exc:
        write_attempt_stderr(attempt_stderr_path, stderr_path, traceback.format_exc())
        code = exc.code if isinstance(exc, WorkerError) else align_error_code(exc)
        message = (
            exc.message if isinstance(exc, WorkerError) else alignment_failure_message(exc)
        )
        write_failure_status(
            job_dir,
            code,
            message,
            request=request,
            attempt_id=attempt_id,
            attempt_stderr_path=attempt_stderr_path,
        )


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
        write_terminal_marker(job_dir, WorkerStatus.SUCCEEDED)
        report_warnings = result.report.get("warnings", [])
        warning_count = len(report_warnings) if isinstance(report_warnings, list) else 0
        write_status(
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
        )
        append_event(
            job_dir,
            WorkerEventType.TASK_COMPLETED,
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
        write_terminal_marker(job_dir, WorkerStatus.ABANDONED)
        write_status(
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
        )
        append_event(
            job_dir,
            WorkerEventType.TASK_ABANDONED,
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
    write_status(job_dir, payload)
    append_event(
        job_dir,
        WorkerEventType.TASK_FAILED,
        level="ERROR",
        message=message,
        details={"code": code, "stderrPath": error["stderrPath"]},
        flush=True,
    )
    write_terminal_marker(job_dir, WorkerStatus.FAILED)


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

    def __enter__(self) -> HeartbeatThread:
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        self._thread.join(timeout=1.0)

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
    }:
        return
    marker = job_dir / status.value
    marker.write_text(f"{status.value} at {utc_now()}\n", encoding="utf-8")


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
