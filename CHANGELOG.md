# Changelog

## 0.6.1

- Bundled the NLTK `punkt_tab` resource in the official Docker image so WhisperX alignment does
  not attempt a runtime download in network-restricted Worker deployments.
- Added final-image, non-root, and network-disabled smoke tests for English `PunktTokenizer` plus
  WhisperX and TorchCodec imports.
- Kept `ALIGNMENT_FAILED` while ensuring missing-resource failures always expose a useful status
  message and retain the complete traceback only in stderr.
- Preserved the v0.6.0 lyric-header, presentation-hint, and Worker observability protocols.

## 0.6.0

- Classify trusted input as LRC metadata, non-singing header, or singing lyric before CTC.
- Preserve leading credit blocks in LRC and structured output without creating SWLRC tokens.
- Add display-only intro hints and `firstAlignedLyricStartMs` to CLI/Worker results and reports.

## 0.5.0

- Added Worker `schemaVersion: 3` for `LYRIC_DRAFT_EXTRACTION` preset and
  advanced override configuration while preserving schema v1/v2 compatibility.
- Upgraded `status.json` into the single authoritative current-state snapshot
  with `statusSchemaVersion`, `requestSchemaVersion`, stable `state` and
  `stage`, attempt metadata, `startedAt`, `stageStartedAt`, `updatedAt`,
  `heartbeatAt`, `requestedConfig`, `resolvedConfig`, `warnings`, `error`, and
  `result`.
- Added append-only `/jobs/{jobId}/events.jsonl` lifecycle events for task
  acceptance, stage changes, terminal states, warnings, failures, and abandoned
  jobs.
- Changed stale-job detection to prefer `status.json.heartbeatAt`, using the
  older `RUNNING` marker mtime only as a compatibility fallback.
- Added shared ASR draft extraction config resolution for CLI and Worker,
  including `FAST`, `RECOMMENDED`, `HIGH_QUALITY`, and `FULL_RECOGNITION`
  presets plus explicit override handling that preserves `false` values.
- Wrote requested and resolved draft extraction config into Worker status and
  candidate draft reports.
- Documented Worker status/events semantics, stage enums, error codes, preset
  behavior, schema compatibility, and the no-fake-progress rule.

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
