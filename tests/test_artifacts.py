from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from xingyu_lyrics_aligner.schemas.artifacts import (
    ArtifactKind,
    ResultArtifact,
    ResultArtifacts,
)
from xingyu_lyrics_aligner.worker import WorkerError, build_desktop_artifacts


def test_artifacts_serialize_with_independent_schema_version(tmp_path: Path) -> None:
    job = tmp_path / "job"
    output = job / "result"
    output.mkdir(parents=True)
    lrc = output / "lyrics.lrc"
    lrc.write_text("[00:00.00]星语\n", encoding="utf-8")

    artifacts = build_desktop_artifacts(job, {"lrc": lrc})

    assert artifacts.model_dump(mode="json", by_alias=True) == {
        "artifactsSchemaVersion": 1,
        "artifacts": [
            {
                "id": "lyrics.lrc",
                "kind": "LRC",
                "relativePath": "result/lyrics.lrc",
                "mediaType": "text/plain",
                "exportable": True,
                "temporary": False,
            }
        ],
    }


@pytest.mark.parametrize("path", ["/tmp/lyrics.lrc", "../lyrics.lrc", "result/../secret"])
def test_artifact_rejects_unsafe_paths(path: str) -> None:
    with pytest.raises(ValidationError):
        ResultArtifact(
            id="lyrics.lrc",
            kind=ArtifactKind.LRC,
            relativePath=path,
            mediaType="text/plain",
        )


def test_artifact_builder_rejects_missing_file(tmp_path: Path) -> None:
    job = tmp_path / "job"
    job.mkdir()

    with pytest.raises(WorkerError, match="Artifact does not exist"):
        build_desktop_artifacts(job, {"lrc": job / "result" / "lyrics.lrc"})


def test_artifacts_model_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ResultArtifacts.model_validate(
            {"artifactsSchemaVersion": 1, "artifacts": [], "unknown": True}
        )
