# Changelog

## Unreleased — 0.7.0

### macOS Desktop MVP

- Add a native SwiftUI App for Apple Silicon and macOS 14+, with audio drag/drop and file
  selection, trusted TXT/LRC lyric import, LRC/SWLRC export, optional vocals/accompaniment
  export, observable progress, cancellation, Finder export opening, and next-song reset.
- Add managed model readiness and explicit installation. Model weights remain outside the App
  under Application Support and are not bundled in the unsigned DMG.
- Embed Python 3.11, FFmpeg/FFprobe 7.1.3, and an LGPL-only locally built PyAV wheel in an
  arm64 Runtime. The candidate is ad-hoc signed only, is not notarized, and is not Gatekeeper
  trusted.

### Worker and protocol

- Add schema v3 `DESKTOP_LYRIC_PROCESSING`, artifacts schema v1, optional formal vocals and
  accompaniment exports, truthful alignment stages, and cooperative cancellation.
- Add terminal Worker values `CANCELLED` and `TASK_CANCELLED`. Consumers with closed status/event
  enums must accept these new schema v3 values before using Desktop cancellation.
- Load the alignment model explicitly before the `ALIGNING` stage. Model loading is idempotent and
  retains the existing cache-only behavior.
- Treat formal artifact export as a commit boundary: cancellation before it yields `CANCELLED`;
  cancellation after it does not override a verified success/review result, and export errors win
  over a simultaneously arriving cancellation request.
- Add versioned Runtime metadata, unique terminal marker commits, symlink/path containment, formal
  `result/audio/vocals.wav` and `result/audio/accompaniment.wav`, process-group cleanup, and atomic
  artifact export while preserving schema v1/v2/v3 and `result.files` compatibility.

### Runtime and release safety

- Add a hash-locked wheelhouse, strict per-distribution license inventory, complete Runtime file
  inventory, GPL codec rejection, controlled FFmpeg cache manifests, and same-machine clean-build
  comparison. This controls build inputs; it is not a claim of cross-machine bit-for-bit
  reproducibility.
- Add model content hashes, symlink and HTTPS downgrade defenses, crash-recoverable installation
  transactions, bounded asynchronous process output, and non-blocking Swift file operations.
- Add an unsigned DMG workflow, inside-out ad-hoc signing, explicit Gatekeeper limitations,
  checksums, and release metadata. No Developer ID signature or notarization is claimed.

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
