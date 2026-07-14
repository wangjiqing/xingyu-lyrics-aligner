from __future__ import annotations

import hashlib
import json
import os
import signal
from pathlib import Path

import pytest
from pytest import MonkeyPatch
from typer.testing import CliRunner

from xingyu_lyrics_aligner.cli import app
from xingyu_lyrics_aligner.desktop_models import (
    ALIGNMENT_MODEL_ID,
    ALIGNMENT_REVISION,
    MODEL_MANIFESTS,
    SEPARATION_MODEL_ID,
    DesktopDataPaths,
    HttpsOnlyRedirectHandler,
    ManifestFile,
    ModelCorruptedError,
    ModelState,
    atomic_replace_directory,
    desktop_readiness,
    inspect_model,
    install_model,
    load_runtime_manifest,
    managed_environment,
    model_manifest,
    recover_model_transaction,
    validate_model_directory,
)


class FakeDownloader:
    def __init__(self, *, total: int | None = 100, fail: bool = False) -> None:
        self.total = total
        self.fail = fail

    def download(self, manifest: object, destination: Path, progress: object) -> None:
        if self.fail:
            raise RuntimeError("download failed")
        for item in manifest.required_files:
            path = destination / item.relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("wb") as stream:
                stream.truncate(item.minimum_size_bytes)
        progress(50, self.total)


class CancelDownloader:
    def download(self, manifest: object, destination: Path, progress: object) -> None:
        raise KeyboardInterrupt


class SignalDownloader:
    def download(self, manifest: object, destination: Path, progress: object) -> None:
        os.kill(os.getpid(), signal.SIGTERM)


def paths(tmp_path: Path) -> DesktopDataPaths:
    return DesktopDataPaths.resolve(tmp_path / "中文 Models with spaces")


def write_installed(
    tmp_path: Path,
    model_id: str,
    *,
    revision: str | None = None,
    missing: str | None = None,
    too_small: str | None = None,
) -> tuple[DesktopDataPaths, Path]:
    resolved = paths(tmp_path)
    manifest = model_manifest(model_id)
    target = resolved.model_dir(manifest)
    target.mkdir(parents=True)
    for item in manifest.required_files:
        if item.relative_path == missing:
            continue
        path = target / item.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as stream:
            stream.truncate(1 if item.relative_path == too_small else item.minimum_size_bytes)
    (target / "install-state.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "modelId": model_id,
                "revision": revision or manifest.source.revision,
            }
        ),
        encoding="utf-8",
    )
    return resolved, target


def test_manifests_are_pinned_versioned_and_use_real_required_files() -> None:
    assert {manifest.manifest_schema_version for manifest in MODEL_MANIFESTS} == {1}
    alignment = model_manifest(ALIGNMENT_MODEL_ID)
    separation = model_manifest(SEPARATION_MODEL_ID)
    assert alignment.source.revision == ALIGNMENT_REVISION
    assert len(alignment.source.revision) == 40
    assert {item.relative_path for item in alignment.required_files} >= {
        "config.json",
        "preprocessor_config.json",
        "pytorch_model.bin",
        "vocab.json",
    }
    assert separation.source.revision and separation.required_files[0].relative_path.endswith(".th")


def test_not_installed_and_stale_download_states(tmp_path: Path) -> None:
    resolved = paths(tmp_path)
    manifest = model_manifest(ALIGNMENT_MODEL_ID)
    assert inspect_model(manifest, resolved)["state"] == ModelState.NOT_INSTALLED
    resolved.staging_dir(manifest).mkdir(parents=True)
    assert inspect_model(manifest, resolved)["state"] == ModelState.DOWNLOADING


def stub_manifest_hashes(monkeypatch: MonkeyPatch) -> None:
    expected = {
        item.relative_path: item.sha256
        for manifest in MODEL_MANIFESTS
        for item in manifest.required_files
    }
    monkeypatch.setattr(
        "xingyu_lyrics_aligner.desktop_models.file_sha256", lambda path: expected[path.name]
    )


def test_installed_incomplete_revision_mismatch_and_corrupted(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    stub_manifest_hashes(monkeypatch)
    resolved, _ = write_installed(tmp_path / "installed", ALIGNMENT_MODEL_ID)
    assert (
        inspect_model(model_manifest(ALIGNMENT_MODEL_ID), resolved)["state"] == ModelState.INSTALLED
    )

    resolved, _ = write_installed(tmp_path / "missing", ALIGNMENT_MODEL_ID, missing="config.json")
    assert (
        inspect_model(model_manifest(ALIGNMENT_MODEL_ID), resolved)["state"]
        == ModelState.INCOMPLETE
    )

    resolved, _ = write_installed(tmp_path / "revision", ALIGNMENT_MODEL_ID, revision="wrong")
    assert (
        inspect_model(model_manifest(ALIGNMENT_MODEL_ID), resolved)["state"]
        == ModelState.REVISION_MISMATCH
    )

    resolved, _ = write_installed(tmp_path / "small", ALIGNMENT_MODEL_ID, too_small="config.json")
    assert (
        inspect_model(model_manifest(ALIGNMENT_MODEL_ID), resolved)["state"] == ModelState.CORRUPTED
    )


def test_readiness_json_and_ffmpeg_ffprobe_presence(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    stub_manifest_hashes(monkeypatch)
    resolved, _ = write_installed(tmp_path, ALIGNMENT_MODEL_ID)
    monkeypatch.setattr(
        "xingyu_lyrics_aligner.desktop_models.shutil.which",
        lambda name: f"/fake/{name}",
    )
    monkeypatch.setattr("xingyu_lyrics_aligner.desktop_models.os.access", lambda path, mode: True)
    monkeypatch.setattr(
        "xingyu_lyrics_aligner.desktop_models.subprocess.run",
        lambda *args, **kwargs: type(
            "Result", (), {"stdout": "ffmpeg version fake\n", "stderr": ""}
        )(),
    )

    readiness = desktop_readiness(resolved)

    assert readiness["schemaVersion"] == 1
    assert readiness["runtime"]["ffmpeg"]["available"] is True
    assert readiness["runtime"]["ffprobe"]["available"] is True
    assert readiness["readyForAlignment"] is True
    assert readiness["readyForSeparation"] is False


def test_installed_model_reports_runtime_package_separately(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    stub_manifest_hashes(monkeypatch)
    resolved, _ = write_installed(tmp_path, SEPARATION_MODEL_ID)
    monkeypatch.setattr(
        "xingyu_lyrics_aligner.desktop_models.importlib.util.find_spec",
        lambda name: None if name == "demucs" else object(),
    )

    model = inspect_model(model_manifest(SEPARATION_MODEL_ID), resolved)

    assert model["state"] == ModelState.INSTALLED
    assert model["problems"] == ["demucs_package_missing"]


@pytest.mark.parametrize(("missing", "field"), [("ffmpeg", "ffmpeg"), ("ffprobe", "ffprobe")])
def test_readiness_reports_missing_media_tool(
    monkeypatch: MonkeyPatch, tmp_path: Path, missing: str, field: str
) -> None:
    monkeypatch.setattr(
        "xingyu_lyrics_aligner.desktop_models.shutil.which",
        lambda name: None if name == missing else f"/fake/{name}",
    )
    monkeypatch.setattr("xingyu_lyrics_aligner.desktop_models.os.access", lambda path, mode: True)
    readiness = desktop_readiness(paths(tmp_path))
    assert readiness["runtime"][field]["available"] is False
    assert readiness["readyForAlignment"] is False


def test_readiness_prefers_explicit_ffmpeg_and_ffprobe(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    ffmpeg = tmp_path / "Bundle Runtime/bin/ffmpeg"
    ffprobe = tmp_path / "Bundle Runtime/bin/ffprobe"
    ffmpeg.parent.mkdir(parents=True)
    ffmpeg.write_text("binary", encoding="utf-8")
    ffprobe.write_text("binary", encoding="utf-8")
    monkeypatch.setenv("XINGYU_ALIGNER_FFMPEG", str(ffmpeg))
    monkeypatch.setenv("XINGYU_ALIGNER_FFPROBE", str(ffprobe))
    monkeypatch.setattr("xingyu_lyrics_aligner.desktop_models.os.access", lambda path, mode: True)
    monkeypatch.setattr(
        "xingyu_lyrics_aligner.desktop_models.subprocess.run",
        lambda *args, **kwargs: type("Result", (), {"stdout": "version pinned\n", "stderr": ""})(),
    )

    readiness = desktop_readiness(paths(tmp_path))

    assert readiness["runtime"]["ffmpeg"]["path"] == str(ffmpeg)
    assert readiness["runtime"]["ffprobe"]["path"] == str(ffprobe)


@pytest.mark.parametrize("total", [100, None])
def test_model_install_success_and_real_progress_shape(
    monkeypatch: MonkeyPatch, tmp_path: Path, total: int | None
) -> None:
    stub_manifest_hashes(monkeypatch)
    events: list[dict[str, object]] = []
    resolved = paths(tmp_path)
    install_model(
        ALIGNMENT_MODEL_ID,
        paths=resolved,
        downloader=FakeDownloader(total=total),
        emit=lambda line: events.append(json.loads(line)),
    )
    assert (
        inspect_model(model_manifest(ALIGNMENT_MODEL_ID), resolved)["state"] == ModelState.INSTALLED
    )
    progress = next(event for event in events if event["type"] == "DOWNLOAD_PROGRESS")
    assert progress == {
        "type": "DOWNLOAD_PROGRESS",
        "modelId": ALIGNMENT_MODEL_ID,
        "downloadedBytes": 50,
        "totalBytes": total,
    }
    assert events[-1]["type"] == "INSTALL_SUCCEEDED"
    assert not resolved.staging_dir(model_manifest(ALIGNMENT_MODEL_ID)).exists()


def test_install_failure_and_cancel_never_mark_installed(tmp_path: Path) -> None:
    resolved = paths(tmp_path)
    events: list[dict[str, object]] = []
    with pytest.raises(RuntimeError, match="download failed"):
        install_model(
            ALIGNMENT_MODEL_ID,
            paths=resolved,
            downloader=FakeDownloader(fail=True),
            emit=lambda line: events.append(json.loads(line)),
        )
    assert events[-1]["type"] == "INSTALL_FAILED"
    assert (
        inspect_model(model_manifest(ALIGNMENT_MODEL_ID), resolved)["state"]
        == ModelState.NOT_INSTALLED
    )
    with pytest.raises(KeyboardInterrupt):
        install_model(
            ALIGNMENT_MODEL_ID,
            paths=resolved,
            downloader=CancelDownloader(),
            emit=lambda line: events.append(json.loads(line)),
        )
    assert events[-1]["type"] == "INSTALL_CANCELLED"
    assert (
        inspect_model(model_manifest(ALIGNMENT_MODEL_ID), resolved)["state"]
        == ModelState.NOT_INSTALLED
    )


def test_sigterm_install_records_cancel_and_restores_handler(tmp_path: Path) -> None:
    resolved = paths(tmp_path)
    events: list[dict[str, object]] = []
    previous = signal.getsignal(signal.SIGTERM)
    with pytest.raises(KeyboardInterrupt):
        install_model(
            ALIGNMENT_MODEL_ID,
            paths=resolved,
            downloader=SignalDownloader(),
            emit=lambda line: events.append(json.loads(line)),
        )
    assert events[-1]["type"] == "INSTALL_CANCELLED"
    assert signal.getsignal(signal.SIGTERM) == previous
    transaction = json.loads(
        resolved.transaction_path(model_manifest(ALIGNMENT_MODEL_ID)).read_text()
    )
    assert transaction["state"] == "CANCELLED"


def test_install_lock_rejects_competing_process(tmp_path: Path) -> None:
    resolved = paths(tmp_path)
    manifest = model_manifest(ALIGNMENT_MODEL_ID)
    resolved.transaction_path(manifest).with_suffix(".lock").mkdir(parents=True)
    with pytest.raises(RuntimeError, match="Another installation"):
        install_model(ALIGNMENT_MODEL_ID, paths=resolved, downloader=FakeDownloader())


def test_journal_failure_after_backup_restores_old_model(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    stub_manifest_hashes(monkeypatch)
    resolved = paths(tmp_path)
    manifest = model_manifest(ALIGNMENT_MODEL_ID)
    target = resolved.model_dir(manifest)
    target.mkdir(parents=True)
    (target / "old.marker").write_text("old")
    transaction = resolved.transaction_path(manifest)
    from xingyu_lyrics_aligner import desktop_models

    real_write = desktop_models.atomic_write_json

    def fail_activating(path: Path, payload: dict[str, object]) -> None:
        if path == transaction and payload.get("state") == "ACTIVATING":
            raise OSError("journal unavailable")
        real_write(path, payload)

    monkeypatch.setattr(desktop_models, "atomic_write_json", fail_activating)
    with pytest.raises(OSError, match="journal unavailable"):
        install_model(ALIGNMENT_MODEL_ID, paths=resolved, downloader=FakeDownloader())
    assert (target / "old.marker").read_text() == "old"


def test_failed_atomic_switch_preserves_installed_model(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "target"
    staging = tmp_path / "staging"
    target.mkdir()
    staging.mkdir()
    (target / "old").write_text("old", encoding="utf-8")
    (staging / "new").write_text("new", encoding="utf-8")
    real_replace = os.replace

    def fail_new(source: Path, destination: Path) -> None:
        if Path(source) == staging:
            raise OSError("switch failed")
        real_replace(source, destination)

    monkeypatch.setattr("xingyu_lyrics_aligner.desktop_models.os.replace", fail_new)
    with pytest.raises(OSError, match="switch failed"):
        atomic_replace_directory(staging, target)
    assert (target / "old").read_text(encoding="utf-8") == "old"


def test_managed_environment_uses_only_app_directories(tmp_path: Path) -> None:
    resolved = paths(tmp_path)
    environment = managed_environment(resolved)
    assert set(environment) >= {
        "HF_HOME",
        "HUGGINGFACE_HUB_CACHE",
        "TRANSFORMERS_CACHE",
        "TORCH_HOME",
        "XDG_CACHE_HOME",
        "NLTK_DATA",
        "XINGYU_ALIGNMENT_MODEL_DIR",
        "XINGYU_DEMUCS_MODEL_REPO",
    }
    assert all(str(resolved.root) in value for value in environment.values())


def test_runtime_manifest_parsing_and_unsupported_schema(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    manifest = tmp_path / "runtime-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "runtimeVersion": "v1",
                "architecture": "arm64",
                "pythonVersion": "3.11.15",
                "packageVersion": "0.6.1",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("XINGYU_RUNTIME_MANIFEST", str(manifest))
    assert load_runtime_manifest() == {
        "schemaVersion": 1,
        "runtimeVersion": "v1",
        "architecture": "arm64",
        "pythonVersion": "3.11.15",
        "packageVersion": "0.6.1",
    }

    manifest.write_text('{"schemaVersion": 2}', encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported runtime manifest schema"):
        load_runtime_manifest()


def test_content_hash_detects_same_size_mutation_and_cache_invalidation(tmp_path: Path) -> None:
    content = b"trusted-content"
    manifest = model_manifest(ALIGNMENT_MODEL_ID).model_copy(
        update={
            "required_files": [
                ManifestFile.model_validate(
                    {
                        "relativePath": "weight.bin",
                        "minimumSizeBytes": len(content),
                        "sha256": hashlib.sha256(content).hexdigest(),
                    }
                )
            ]
        }
    )
    directory = tmp_path / "model"
    directory.mkdir()
    weight = directory / "weight.bin"
    weight.write_bytes(content)
    (directory / "install-state.json").write_text(
        json.dumps({"revision": manifest.source.revision})
    )
    validate_model_directory(manifest, directory)
    assert (directory / ".integrity-cache.json").is_file()
    weight.write_bytes(b"changed-content")
    os.utime(weight, ns=(weight.stat().st_atime_ns, weight.stat().st_mtime_ns + 1))
    with pytest.raises(ModelCorruptedError, match="checksum"):
        validate_model_directory(manifest, directory)


@pytest.mark.parametrize("inside", [False, True])
def test_model_required_file_rejects_symlink(tmp_path: Path, inside: bool) -> None:
    content = b"valid"
    manifest = model_manifest(ALIGNMENT_MODEL_ID).model_copy(
        update={
            "required_files": [
                ManifestFile.model_validate(
                    {
                        "relativePath": "weight.bin",
                        "minimumSizeBytes": 1,
                        "sha256": hashlib.sha256(content).hexdigest(),
                    }
                )
            ]
        }
    )
    directory = tmp_path / "model"
    directory.mkdir()
    target = (directory / "target.bin") if inside else (tmp_path / "outside.bin")
    target.write_bytes(content)
    (directory / "weight.bin").symlink_to(target)
    (directory / "install-state.json").write_text(
        json.dumps({"revision": manifest.source.revision})
    )
    with pytest.raises(ModelCorruptedError, match="symlink"):
        validate_model_directory(manifest, directory)


def test_model_required_file_rejects_non_regular_file(tmp_path: Path) -> None:
    manifest = model_manifest(ALIGNMENT_MODEL_ID).model_copy(
        update={
            "required_files": [
                ManifestFile.model_validate({"relativePath": "weight.bin", "minimumSizeBytes": 1})
            ]
        }
    )
    directory = tmp_path / "model"
    (directory / "weight.bin").mkdir(parents=True)
    (directory / "install-state.json").write_text(
        json.dumps({"revision": manifest.source.revision})
    )
    with pytest.raises(ModelCorruptedError, match="not_regular"):
        validate_model_directory(manifest, directory)


def test_https_redirect_handler_rejects_downgrade() -> None:
    request = type("Request", (), {"full_url": "https://example.test/model"})()
    with pytest.raises(RuntimeError, match="downgrade"):
        HttpsOnlyRedirectHandler().redirect_request(
            request, None, 302, "Found", {}, "http://example.test/model"
        )


def test_transaction_recovery_restores_backup_and_is_idempotent(tmp_path: Path) -> None:
    resolved = paths(tmp_path)
    manifest = model_manifest(ALIGNMENT_MODEL_ID)
    target = resolved.model_dir(manifest)
    staging = resolved.staging_dir(manifest)
    backup = target.with_name(f".{target.name}.backup")
    backup.mkdir(parents=True)
    (backup / "old").write_text("preserved")
    staging.mkdir(parents=True)
    transaction = resolved.transaction_path(manifest)
    transaction.parent.mkdir(parents=True)
    transaction.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "modelId": manifest.id,
                "expectedRevision": manifest.source.revision,
                "stagingPath": str(staging),
                "backupPath": str(backup),
                "finalPath": str(target),
                "state": "ACTIVATING",
            }
        )
    )
    recover_model_transaction(manifest, resolved)
    recover_model_transaction(manifest, resolved)
    assert (target / "old").read_text() == "preserved"
    assert not staging.exists() and not transaction.exists()


def test_readiness_cli_is_machine_readable(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        ["desktop", "readiness", "--data-dir", str(tmp_path), "--json"],
    )
    assert result.exit_code == 0
    assert json.loads(result.stdout)["schemaVersion"] == 1
