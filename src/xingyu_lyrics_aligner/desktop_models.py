"""Desktop runtime readiness and versioned local model installation."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


class ModelCategory(StrEnum):
    ALIGNMENT = "ALIGNMENT"
    SEPARATION = "SEPARATION"


class ModelState(StrEnum):
    NOT_INSTALLED = "NOT_INSTALLED"
    DOWNLOADING = "DOWNLOADING"
    INSTALLED = "INSTALLED"
    INCOMPLETE = "INCOMPLETE"
    REVISION_MISMATCH = "REVISION_MISMATCH"
    CORRUPTED = "CORRUPTED"
    UNKNOWN = "UNKNOWN"


class ManifestFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    relative_path: str = Field(alias="relativePath", min_length=1)
    minimum_size_bytes: int = Field(alias="minimumSizeBytes", ge=1)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    lfs_oid: str | None = Field(default=None, alias="lfsOid", pattern=r"^sha256:[0-9a-f]{64}$")


class ModelSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str
    repository: str
    revision: str
    download_url: str | None = Field(default=None, alias="downloadUrl")


class ModelLicense(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    url: str


class DesktopModelManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    manifest_schema_version: Literal[1] = Field(default=1, alias="manifestSchemaVersion")
    id: str
    display_name: str = Field(alias="displayName")
    category: ModelCategory
    required: bool
    estimated_download_bytes: int = Field(alias="estimatedDownloadBytes", ge=1)
    source: ModelSource
    required_files: list[ManifestFile] = Field(alias="requiredFiles", min_length=1)
    license: ModelLicense


ALIGNMENT_MODEL_ID = "alignment.zh.whisperx"
SEPARATION_MODEL_ID = "separation.demucs.htdemucs"
ALIGNMENT_REVISION = "99ccb2737be22b8bb50dcfcc39ad4d567fb90cfd"
DEMUCS_CATALOG_REVISION = "e976d93ecc3865e5757426930257e200846a520a"

MODEL_MANIFESTS = (
    DesktopModelManifest.model_validate(
        {
            "manifestSchemaVersion": 1,
            "id": ALIGNMENT_MODEL_ID,
            "displayName": "中文歌词对齐模型",
            "category": "ALIGNMENT",
            "required": True,
            "estimatedDownloadBytes": 1_276_342_318,
            "source": {
                "provider": "huggingface",
                "repository": "jonatasgrosman/wav2vec2-large-xlsr-53-chinese-zh-cn",
                "revision": ALIGNMENT_REVISION,
            },
            "requiredFiles": [
                {
                    "relativePath": "config.json",
                    "minimumSizeBytes": 1000,
                    "sha256": "9af98614e322a5300c75605227d93c98af0c8f78754aba1dfc279166688afddd",
                },
                {
                    "relativePath": "preprocessor_config.json",
                    "minimumSizeBytes": 100,
                    "sha256": "c403ce09975b90dff0dd8302c42d422e9de1f166cd7772df23490069893cb0cf",
                },
                {
                    "relativePath": "pytorch_model.bin",
                    "minimumSizeBytes": 1_200_000_000,
                    "sha256": "de031fd4b29e0c0667e5346450fadfe1326c89936b888b59c4ede608db763ee4",
                    "lfsOid": (
                        "sha256:de031fd4b29e0c0667e5346450fadfe1326c89936b888b59c4ede608db763ee4"
                    ),
                },
                {
                    "relativePath": "special_tokens_map.json",
                    "minimumSizeBytes": 50,
                    "sha256": "bb7068de1150661a10b55f9e4b12a0e77af8bf91f5e45e1b58afaf1d0e17f675",
                },
                {
                    "relativePath": "vocab.json",
                    "minimumSizeBytes": 40_000,
                    "sha256": "33fea3444869c2cd2433f59da079b04ce91515f946d21fe1b0ff3825398bcec7",
                },
            ],
            "license": {
                "name": "Apache-2.0",
                "url": "https://huggingface.co/jonatasgrosman/"
                "wav2vec2-large-xlsr-53-chinese-zh-cn/blob/"
                f"{ALIGNMENT_REVISION}/README.md",
            },
        }
    ),
    DesktopModelManifest.model_validate(
        {
            "manifestSchemaVersion": 1,
            "id": SEPARATION_MODEL_ID,
            "displayName": "人声分离模型 htdemucs",
            "category": "SEPARATION",
            "required": False,
            "estimatedDownloadBytes": 84_141_911,
            "source": {
                "provider": "facebookresearch",
                "repository": "facebookresearch/demucs",
                "revision": DEMUCS_CATALOG_REVISION,
                "downloadUrl": "https://dl.fbaipublicfiles.com/demucs/"
                "hybrid_transformer/955717e8-8726e21a.th",
            },
            "requiredFiles": [
                {
                    "relativePath": "955717e8-8726e21a.th",
                    "minimumSizeBytes": 84_000_000,
                    "sha256": "8726e21a993978c7ba086d3872e7608d7d5bfca646ca4aca459ffda844faa8b4",
                },
                {
                    "relativePath": "htdemucs.yaml",
                    "minimumSizeBytes": 20,
                    "sha256": "239c445d0b14454d541ad8bd9bb271c9e536d267e8a4625208744cbb2e7bb66c",
                },
            ],
            "license": {
                "name": "MIT",
                "url": "https://github.com/facebookresearch/demucs/blob/"
                f"{DEMUCS_CATALOG_REVISION}/LICENSE",
            },
        }
    ),
)


@dataclass(frozen=True)
class DesktopDataPaths:
    root: Path
    models: Path
    manifests: Path
    downloads: Path
    runtime: Path
    logs: Path

    @classmethod
    def resolve(cls, root: Path | None = None) -> DesktopDataPaths:
        resolved = root or Path(
            os.environ.get(
                "XINGYU_APP_SUPPORT_DIR",
                Path.home() / "Library/Application Support/XingyuLyricsAligner",
            )
        )
        return cls(
            root=resolved,
            models=resolved / "Models",
            manifests=resolved / "ModelManifests",
            downloads=resolved / "Downloads",
            runtime=resolved / "Runtime",
            logs=resolved / "Logs",
        )

    def model_dir(self, manifest: DesktopModelManifest) -> Path:
        category = "Alignment" if manifest.category == ModelCategory.ALIGNMENT else "Separation"
        return self.models / category / manifest.id

    def staging_dir(self, manifest: DesktopModelManifest) -> Path:
        return self.downloads / f"{manifest.id}.partial"

    def transaction_dir(self) -> Path:
        return self.models / ".transactions"

    def transaction_path(self, manifest: DesktopModelManifest) -> Path:
        return self.transaction_dir() / f"{manifest.id}.json"


class DownloadProgress(Protocol):
    def __call__(self, downloaded: int, total: int | None) -> None: ...


class ModelDownloader(Protocol):
    def download(
        self,
        manifest: DesktopModelManifest,
        destination: Path,
        progress: DownloadProgress,
    ) -> None: ...


class HttpModelDownloader:
    """Stream pinned public model files while reporting real byte counts."""

    def download(
        self,
        manifest: DesktopModelManifest,
        destination: Path,
        progress: DownloadProgress,
    ) -> None:
        downloaded = 0
        for item in manifest.required_files:
            if manifest.id == SEPARATION_MODEL_ID and item.relative_path == "htdemucs.yaml":
                content = b"models: ['955717e8']\n"
                (destination / item.relative_path).write_bytes(content)
                continue
            url = model_file_url(manifest, item.relative_path)
            target = destination / item.relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            request = urllib.request.Request(url, headers={"User-Agent": "xingyu-align/desktop"})
            if urllib.parse.urlparse(url).scheme != "https":
                raise RuntimeError("Model downloads require HTTPS.")
            opener = urllib.request.build_opener(HttpsOnlyRedirectHandler())
            with opener.open(request, timeout=60) as response, target.open("wb") as out:
                final_url = response.geturl()
                if urllib.parse.urlparse(final_url).scheme != "https":
                    raise RuntimeError("Model download redirected to an insecure URL.")
                while chunk := response.read(1024 * 1024):
                    out.write(chunk)
                    downloaded += len(chunk)
                    progress(downloaded, manifest.estimated_download_bytes)


class HttpsOnlyRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> Any:
        if (
            urllib.parse.urlparse(req.full_url).scheme == "https"
            and urllib.parse.urlparse(newurl).scheme != "https"
        ):
            raise RuntimeError("Model download redirect attempted to downgrade HTTPS.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def model_file_url(manifest: DesktopModelManifest, relative_path: str) -> str:
    if manifest.source.provider == "huggingface":
        return (
            f"https://huggingface.co/{manifest.source.repository}/resolve/"
            f"{manifest.source.revision}/{relative_path}"
        )
    if manifest.source.download_url is None:
        raise ValueError(f"No download URL for {manifest.id}")
    return manifest.source.download_url


def managed_environment(paths: DesktopDataPaths) -> dict[str, str]:
    cache = paths.root / "Cache"
    return {
        "XINGYU_APP_SUPPORT_DIR": str(paths.root),
        "XINGYU_ALIGNMENT_MODEL_DIR": str(paths.model_dir(model_manifest(ALIGNMENT_MODEL_ID))),
        "XINGYU_DEMUCS_MODEL_REPO": str(paths.model_dir(model_manifest(SEPARATION_MODEL_ID))),
        "HF_HOME": str(cache / "huggingface"),
        "HUGGINGFACE_HUB_CACHE": str(cache / "huggingface/hub"),
        "TRANSFORMERS_CACHE": str(cache / "huggingface/transformers"),
        "TORCH_HOME": str(cache / "torch"),
        "XDG_CACHE_HOME": str(cache),
        "NLTK_DATA": str(paths.runtime / "nltk_data"),
    }


def model_manifest(model_id: str) -> DesktopModelManifest:
    for manifest in MODEL_MANIFESTS:
        if manifest.id == model_id:
            return manifest
    raise ValueError(f"Unknown desktop model ID: {model_id}")


def write_manifests(paths: DesktopDataPaths) -> None:
    paths.manifests.mkdir(parents=True, exist_ok=True)
    for manifest in MODEL_MANIFESTS:
        atomic_write_json(
            paths.manifests / f"{manifest.id}.json",
            manifest.model_dump(mode="json", by_alias=True),
        )


def inspect_model(manifest: DesktopModelManifest, paths: DesktopDataPaths) -> dict[str, Any]:
    recover_model_transaction(manifest, paths)
    target = paths.model_dir(manifest)
    staging = paths.staging_dir(manifest)
    base = {
        "id": manifest.id,
        "displayName": manifest.display_name,
        "category": manifest.category,
        "required": manifest.required,
        "estimatedDownloadBytes": manifest.estimated_download_bytes,
        "expectedRevision": manifest.source.revision,
        "path": str(target),
        "license": manifest.license.model_dump(mode="json"),
        "problems": [],
    }
    if staging.exists() and not target.exists():
        return base | {"state": ModelState.DOWNLOADING, "installedRevision": None}
    if not target.exists():
        return base | {"state": ModelState.NOT_INSTALLED, "installedRevision": None}
    state_path = target / "install-state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return base | {
            "state": ModelState.INCOMPLETE,
            "installedRevision": None,
            "problems": ["install_state_missing"],
        }
    except (json.JSONDecodeError, OSError):
        return base | {
            "state": ModelState.UNKNOWN,
            "installedRevision": None,
            "problems": ["install_state_invalid"],
        }
    revision = state.get("revision")
    if revision != manifest.source.revision:
        return base | {
            "state": ModelState.REVISION_MISMATCH,
            "installedRevision": revision,
            "problems": ["revision_mismatch"],
        }
    try:
        validate_model_directory(manifest, target)
    except ModelIncompleteError as exc:
        return base | {
            "state": ModelState.INCOMPLETE,
            "installedRevision": revision,
            "problems": [str(exc)],
        }
    except ModelCorruptedError as exc:
        return base | {
            "state": ModelState.CORRUPTED,
            "installedRevision": revision,
            "problems": [str(exc)],
        }
    problems: list[str] = []
    if manifest.id == ALIGNMENT_MODEL_ID and importlib.util.find_spec("whisperx") is None:
        problems.append("whisperx_package_missing")
    if manifest.id == SEPARATION_MODEL_ID and importlib.util.find_spec("demucs") is None:
        problems.append("demucs_package_missing")
    return base | {
        "state": ModelState.INSTALLED,
        "installedRevision": revision,
        "problems": problems,
    }


def executable_status(name: str, environment_name: str | None = None) -> dict[str, Any]:
    configured = os.environ.get(environment_name) if environment_name else None
    path = configured or shutil.which(name)
    if path is None:
        return {"available": False, "path": None, "version": None}
    if configured and (not os.path.isfile(path) or not os.access(path, os.X_OK)):
        return {"available": False, "path": path, "version": None}
    try:
        result = subprocess.run(
            [path, "-version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        first_line = (result.stdout or result.stderr).splitlines()[0]
    except (OSError, subprocess.TimeoutExpired, IndexError):
        first_line = None
    return {"available": os.access(path, os.X_OK), "path": path, "version": first_line}


def desktop_readiness(paths: DesktopDataPaths | None = None) -> dict[str, Any]:
    resolved = paths or DesktopDataPaths.resolve()
    write_manifests(resolved)
    models = [inspect_model(manifest, resolved) for manifest in MODEL_MANIFESTS]
    by_id = {item["id"]: item for item in models}
    ffmpeg = executable_status("ffmpeg", "XINGYU_ALIGNER_FFMPEG")
    ffprobe = executable_status("ffprobe", "XINGYU_ALIGNER_FFPROBE")
    runtime_ready = sys.version_info >= (3, 11) and sys.version_info < (3, 14)
    runtime_manifest = load_runtime_manifest()
    alignment = by_id[ALIGNMENT_MODEL_ID]
    alignment_ready = alignment["state"] == ModelState.INSTALLED and not alignment["problems"]
    separation = by_id[SEPARATION_MODEL_ID]
    separation_ready = separation["state"] == ModelState.INSTALLED and not separation["problems"]
    return {
        "schemaVersion": 1,
        "runtime": {
            "python": {
                "available": runtime_ready,
                "version": platform.python_version(),
                "path": sys.executable,
            },
            "ffmpeg": ffmpeg,
            "ffprobe": ffprobe,
            "developmentRuntime": runtime_manifest is None,
            "runtimeManifest": runtime_manifest,
        },
        "models": models,
        "readyForAlignment": runtime_ready
        and ffmpeg["available"]
        and ffprobe["available"]
        and alignment_ready,
        "readyForSeparation": runtime_ready
        and ffmpeg["available"]
        and ffprobe["available"]
        and separation_ready,
        "managedEnvironment": managed_environment(resolved),
    }


def load_runtime_manifest() -> dict[str, Any] | None:
    configured = os.environ.get("XINGYU_RUNTIME_MANIFEST")
    if not configured:
        return None
    path = Path(configured)
    payload = json.loads(path.read_text(encoding="utf-8"))
    schema = payload.get("schemaVersion")
    if schema != 1:
        raise ValueError(f"Unsupported runtime manifest schema: {schema}")
    required = ("runtimeVersion", "architecture", "pythonVersion", "packageVersion")
    missing = [field for field in required if not payload.get(field)]
    if missing:
        raise ValueError("Runtime manifest is missing: " + ", ".join(missing))
    return {
        "schemaVersion": schema,
        "runtimeVersion": payload["runtimeVersion"],
        "architecture": payload["architecture"],
        "pythonVersion": payload["pythonVersion"],
        "packageVersion": payload["packageVersion"],
    }


def install_model(
    model_id: str,
    *,
    paths: DesktopDataPaths | None = None,
    downloader: ModelDownloader | None = None,
    emit: Callable[[str], None] = print,
) -> None:
    resolved = paths or DesktopDataPaths.resolve()
    manifest = model_manifest(model_id)
    write_manifests(resolved)
    staging = resolved.staging_dir(manifest)
    target = resolved.model_dir(manifest)
    transaction = resolved.transaction_path(manifest)
    lock = transaction.with_suffix(".lock")
    recover_model_transaction(manifest, resolved)
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        lock.mkdir()
    except FileExistsError as exc:
        raise RuntimeError(f"Another installation is active for {model_id}.") from exc
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=False)
    backup = target.with_name(f".{target.name}.backup")
    started_at = utc_now()

    def journal(state: str) -> None:
        atomic_write_json(
            transaction,
            {
                "schemaVersion": 1,
                "modelId": model_id,
                "expectedRevision": manifest.source.revision,
                "stagingPath": str(staging),
                "backupPath": str(backup),
                "finalPath": str(target),
                "startedAt": started_at,
                "updatedAt": utc_now(),
                "processId": os.getpid(),
                "state": state,
            },
        )

    def event(event_type: str, **details: object) -> None:
        emit(
            json.dumps(
                {"type": event_type, "modelId": model_id, **details},
                ensure_ascii=False,
            )
        )

    event("INSTALL_STARTED", revision=manifest.source.revision)
    previous_handlers: dict[signal.Signals, Any] = {}
    if threading_is_main():
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(
                signum, lambda _signum, _frame: (_ for _ in ()).throw(KeyboardInterrupt())
            )
    try:
        journal("DOWNLOADING")
        (downloader or HttpModelDownloader()).download(
            manifest,
            staging,
            lambda downloaded, total: event(
                "DOWNLOAD_PROGRESS",
                downloadedBytes=downloaded,
                totalBytes=total,
            ),
        )
        atomic_write_json(
            staging / "install-state.json",
            {
                "schemaVersion": 1,
                "modelId": model_id,
                "revision": manifest.source.revision,
                "installedAt": utc_now(),
            },
        )
        journal("VERIFYING")
        event("VERIFYING")
        # Validate the staging directory directly without treating it as installed.
        validate_model_directory(manifest, staging)
        event("INSTALLING")
        journal("BACKING_UP")
        target.parent.mkdir(parents=True, exist_ok=True)
        if backup.exists():
            shutil.rmtree(backup)
        if target.exists():
            os.replace(target, backup)
        journal("ACTIVATING")
        try:
            os.replace(staging, target)
            validate_model_directory(manifest, target)
        except BaseException:
            shutil.rmtree(target, ignore_errors=True)
            if backup.exists():
                os.replace(backup, target)
            raise
        journal("COMPLETED")
        shutil.rmtree(backup, ignore_errors=True)
        transaction.unlink(missing_ok=True)
        event("INSTALL_SUCCEEDED", path=str(target))
    except KeyboardInterrupt:
        shutil.rmtree(staging, ignore_errors=True)
        if not target.exists() and backup.exists():
            os.replace(backup, target)
        journal("CANCELLED")
        event("INSTALL_CANCELLED")
        raise
    except Exception as exc:
        shutil.rmtree(staging, ignore_errors=True)
        if not target.exists() and backup.exists():
            os.replace(backup, target)
        journal("FAILED")
        event("INSTALL_FAILED", message=str(exc))
        raise
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
        lock.rmdir()


def validate_model_directory(manifest: DesktopModelManifest, directory: Path) -> None:
    root = directory.resolve(strict=True)
    cache_path = directory / ".integrity-cache.json"
    try:
        cache = (
            json.loads(cache_path.read_text(encoding="utf-8"))
            if not cache_path.is_symlink()
            else {}
        )
    except (OSError, json.JSONDecodeError):
        cache = {}
    cached_files = (
        cache.get("files", {}) if cache.get("revision") == manifest.source.revision else {}
    )
    updated_cache: dict[str, Any] = {}
    for item in manifest.required_files:
        path = directory / item.relative_path
        if path.is_symlink():
            raise ModelCorruptedError(f"symlink:{item.relative_path}")
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(root)
        except (FileNotFoundError, ValueError):
            raise ModelIncompleteError(f"missing:{item.relative_path}") from None
        if not resolved.is_file():
            raise ModelCorruptedError(f"not_regular:{item.relative_path}")
        if path.stat().st_size < item.minimum_size_bytes:
            raise ModelCorruptedError(f"too_small:{item.relative_path}")
        expected = item.sha256 or (item.lfs_oid.removeprefix("sha256:") if item.lfs_oid else None)
        stat = resolved.stat()
        cache_key = {"size": stat.st_size, "mtimeNs": stat.st_mtime_ns, "expected": expected}
        cached = cached_files.get(item.relative_path)
        actual = (
            cached.get("actual")
            if isinstance(cached, dict) and all(cached.get(k) == v for k, v in cache_key.items())
            else None
        )
        if expected and actual is None:
            actual = file_sha256(resolved)
        if expected and actual != expected:
            raise ModelCorruptedError(f"checksum:{item.relative_path}")
        updated_cache[item.relative_path] = {**cache_key, "actual": actual}
    state = json.loads((directory / "install-state.json").read_text(encoding="utf-8"))
    if state.get("revision") != manifest.source.revision:
        raise RuntimeError("Installed model revision does not match manifest.")
    atomic_write_json(
        cache_path,
        {"schemaVersion": 1, "revision": manifest.source.revision, "files": updated_cache},
    )


class ModelIncompleteError(RuntimeError):
    pass


class ModelCorruptedError(RuntimeError):
    pass


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def recover_model_transaction(manifest: DesktopModelManifest, paths: DesktopDataPaths) -> None:
    journal_path = paths.transaction_path(manifest)
    if not journal_path.exists():
        return
    try:
        payload = json.loads(journal_path.read_text(encoding="utf-8"))
        if payload.get("schemaVersion") != 1 or payload.get("modelId") != manifest.id:
            raise ValueError("Invalid model transaction journal.")
        process_id = payload.get("processId")
        if isinstance(process_id, int) and process_id > 0:
            try:
                os.kill(process_id, 0)
            except ProcessLookupError:
                pass
            except PermissionError:
                return
            else:
                command = subprocess.run(
                    ["/bin/ps", "-p", str(process_id), "-o", "command="],
                    check=False,
                    capture_output=True,
                    text=True,
                ).stdout
                if "models install" in command and manifest.id in command:
                    return
        staging = Path(payload["stagingPath"])
        backup = Path(payload["backupPath"])
        target = Path(payload["finalPath"])
        expected_target = paths.model_dir(manifest)
        expected_staging = paths.staging_dir(manifest)
        expected_backup = expected_target.with_name(f".{expected_target.name}.backup")
        if (staging, backup, target) != (expected_staging, expected_backup, expected_target):
            raise ValueError("Model transaction paths do not match the catalog.")
        if target.exists():
            try:
                validate_model_directory(manifest, target)
            except Exception:
                if backup.exists():
                    shutil.rmtree(target, ignore_errors=True)
                    os.replace(backup, target)
            else:
                shutil.rmtree(backup, ignore_errors=True)
        elif backup.exists():
            os.replace(backup, target)
        shutil.rmtree(staging, ignore_errors=True)
        journal_path.unlink(missing_ok=True)
        shutil.rmtree(journal_path.with_suffix(".lock"), ignore_errors=True)
    except (OSError, KeyError, ValueError, json.JSONDecodeError):
        # An untrusted or unwritable journal must not trigger filesystem operations.
        return


def atomic_replace_directory(staging: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    backup = target.with_name(f".{target.name}.backup-{time.time_ns()}")
    had_target = target.exists()
    if had_target:
        os.replace(target, backup)
    try:
        os.replace(staging, target)
    except Exception:
        if had_target and backup.exists():
            os.replace(backup, target)
        raise
    shutil.rmtree(backup, ignore_errors=True)


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def threading_is_main() -> bool:
    import threading

    return threading.current_thread() is threading.main_thread()
