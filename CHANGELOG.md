# Changelog

## 0.4.0

- Added Worker `schemaVersion: 2` with explicit `taskType` dispatch for
  `LYRICS_ALIGNMENT` and `LYRIC_DRAFT_EXTRACTION`.
- Preserved `schemaVersion: 1` as the v0.3.0 alignment request protocol.
- Added Worker candidate lyric draft extraction, reusing the
  `CandidateLyricsExtractionService` behind the existing `candidate extract`
  command.
- Added strict per-job path validation for `audioPath`, `lyricsPath`,
  `sectionManifestPath`, `outputDir`, job ID matching, and symlink escapes.
- Added draft extraction result validation for `transcript.cleaned.txt`,
  `transcript.raw.txt`, `transcript.segments.json`, and `report.json`.
- Added Worker intermediate vocals policy: cleaned by default, retained only
  under `/jobs/{jobId}/intermediate` when `retainIntermediate` is true.
- Updated the standard Docker image to install both `alignment` and
  `candidate-lyrics` dependencies, including faster-whisper, Demucs, and
  TorchCodec.
- Pinned the final Docker CPU runtime to PyTorch 2.11 and TorchCodec 0.14 CPU
  wheels so TorchCodec imports successfully in `python:3.11-slim-bookworm`.

## 0.3.0

- Added the official CPU Docker image for `xingyu-align`.
- Added `xingyu-align worker run`, an optional shared-directory Worker for
  Docker Compose deployments.
- Added strict Worker path validation for `/music` audio inputs and `/jobs`
  request/output files.
- Added Worker status contract with `SUCCEEDED`, `NEEDS_REVIEW`, `FAILED`, and
  `ABANDONED`.
- Hardened Worker handoff with exclusive `RUNNING` creation, atomic
  `status.json` writes, required output-file validation, and per-attempt stderr
  logs.
- Added Docker Compose Worker examples under `deploy/`.
- Added GitHub Actions CI for Ruff, mypy, pytest, Docker build, and Docker smoke
  tests.
- Added tag-driven GHCR and Docker Hub image publishing for `0.3.0`, `0.3`,
  and `latest`, including Docker Hub anonymous pull verification and best-effort
  GHCR public visibility handling.
- Kept the default macOS CLI and direct Python API path unchanged.

Docker support in v0.3.0 is CPU-first. The release workflow publishes a
multi-architecture manifest for `linux/amd64` and `linux/arm64`, so Apple
Silicon Macs pull the ARM64 image by default.
