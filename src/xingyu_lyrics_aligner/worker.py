"""Shared-directory worker for Docker Compose integrations."""

from __future__ import annotations

import json
import os
import time
import traceback
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from xingyu_lyrics_aligner.api import AlignLyricsOptions, align_lyrics
from xingyu_lyrics_aligner.commands.align import align_error_code, align_json_result_payload
from xingyu_lyrics_aligner.device import DeviceStrategy


class WorkerStatus(StrEnum):
    """Stable status values written to status.json."""

    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    FAILED = "FAILED"
    ABANDONED = "ABANDONED"


class WorkerRequest(BaseModel):
    """Machine contract for /jobs/{jobId}/request.json."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(alias="schemaVersion")
    job_id: str = Field(alias="jobId", min_length=1)
    audio_path: Path = Field(alias="audioPath")
    lyrics_path: Path = Field(alias="lyricsPath")
    output_dir: Path = Field(alias="outputDir")
    language: str = "zh"
    device: DeviceStrategy = DeviceStrategy.CPU
    section_manifest_path: Path | None = Field(default=None, alias="sectionManifestPath")
    created_at: str | None = Field(default=None, alias="createdAt")


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
        write_status(
            job_dir,
            {
                "schemaVersion": 1,
                "jobId": request.job_id,
                "status": WorkerStatus.RUNNING,
                "updatedAt": utc_now(),
            },
        )
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
    """Run one claimed alignment job and write status.json plus stderr.log."""

    job_dir = claimed.job_dir
    request = claimed.request
    attempt_id = new_attempt_id()
    attempt_stderr_path = job_dir / "attempts" / f"{attempt_id}.stderr.log"
    stderr_path = job_dir / "stderr.log"
    attempt_stderr_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        validate_request_paths(request, jobs_root=jobs_root, music_root=music_root)
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
        validate_result_files(result.files)
        write_attempt_stderr(attempt_stderr_path, stderr_path, "")
        payload = align_json_result_payload(result)
        status = classify_result(
            payload,
            min_coverage=min_coverage,
            estimated_token_review_threshold=estimated_token_review_threshold,
        )
        write_status(
            job_dir,
            {
                "schemaVersion": 1,
                "jobId": request.job_id,
                "status": status,
                "updatedAt": utc_now(),
                "attempt": {
                    "id": attempt_id,
                    "stderr": str(attempt_stderr_path),
                },
                "result": payload,
            },
        )
    except Exception as exc:
        write_attempt_stderr(attempt_stderr_path, stderr_path, traceback.format_exc())
        code = exc.code if isinstance(exc, WorkerError) else align_error_code(exc)
        message = exc.message if isinstance(exc, WorkerError) else str(exc)
        write_failure_status(
            job_dir,
            code,
            message,
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
    try:
        request = WorkerRequest.model_validate(data)
    except ValidationError as exc:
        raise WorkerError("REQUEST_INVALID", str(exc)) from exc
    if request.schema_version != 1:
        raise WorkerError("UNSUPPORTED_SCHEMA", "Only worker request schemaVersion 1 is supported.")
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

    require_inside(request.audio_path, music_root, field="audioPath")
    require_inside(request.lyrics_path, jobs_root, field="lyricsPath")
    require_inside(request.output_dir, jobs_root, field="outputDir")
    if request.section_manifest_path is not None:
        require_inside(request.section_manifest_path, jobs_root, field="sectionManifestPath")


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
            "Alignment completed but required output files are missing: "
            + ", ".join(missing),
        )


def mark_abandoned_jobs(jobs_dir: Path, *, timeout_seconds: int) -> None:
    """Mark stale RUNNING jobs as ABANDONED so they do not hang forever."""

    now = time.time()
    for running in jobs_dir.glob("*/RUNNING"):
        age = now - running.stat().st_mtime
        if age < timeout_seconds:
            continue
        job_dir = running.parent
        abandoned = job_dir / "ABANDONED"
        (job_dir / "READY").unlink(missing_ok=True)
        os.replace(running, abandoned)
        job_id = job_dir.name
        write_status(
            job_dir,
            {
                "schemaVersion": 1,
                "jobId": job_id,
                "status": WorkerStatus.ABANDONED,
                "updatedAt": utc_now(),
                "error": {
                    "code": "RUNNING_TIMEOUT",
                    "message": f"RUNNING marker exceeded {timeout_seconds} seconds.",
                    "stderr": str(job_dir / "stderr.log"),
                },
            },
        )


def write_failure_status(
    job_dir: Path,
    code: str,
    message: str,
    *,
    attempt_id: str | None = None,
    attempt_stderr_path: Path | None = None,
) -> None:
    """Write a stable FAILED status.json."""

    payload: dict[str, Any] = {
        "schemaVersion": 1,
        "jobId": job_dir.name,
        "status": WorkerStatus.FAILED,
        "updatedAt": utc_now(),
        "error": {
            "code": code,
            "message": message,
            "stderr": str(job_dir / "stderr.log"),
        },
    }
    if attempt_id is not None and attempt_stderr_path is not None:
        payload["attempt"] = {
            "id": attempt_id,
            "stderr": str(attempt_stderr_path),
        }
        payload["error"]["attemptStderr"] = str(attempt_stderr_path)
    write_status(job_dir, payload)


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
