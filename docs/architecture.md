# Architecture

Xingyu Lyrics Aligner is a local-first CLI and Worker project. It keeps the
audio-library integration at the filesystem boundary: the library creates job
directories, and the Worker reads requests and writes result files.

## Main Flows

Trusted-lyrics alignment:

```text
trusted lyrics + audio
  -> alignment pipeline
  -> alignment.json + lyrics.lrc + lyrics.swlrc + report.json
```

Candidate lyric draft extraction:

```text
audio
  -> optional Demucs vocals separation
  -> faster-whisper transcription
  -> transcript.cleaned.txt + transcript.raw.txt + transcript.segments.json
```

Candidate drafts are untrusted text for manual correction. They do not become
SWLRC and do not replace the trusted-lyrics alignment flow.

## Layers

- `cli.py`: Typer commands, option parsing, and human-readable output.
- `worker.py`: shared-directory protocol, atomic job claiming, path validation,
  status/event writes, heartbeat-based stale detection, and task dispatch.
- `alignment/`: trusted-lyrics alignment pipeline and LRC/SWLRC exporters.
- `candidate_lyrics/transcription.py`: reusable candidate lyric extraction
  service used by both CLI and Worker.
- `candidate_lyrics/config.py`: shared draft extraction preset and override
  resolver used by both CLI and Worker.
- `candidate_lyrics/script_normalization.py`: optional Simplified/Traditional
  review-copy generation for candidate text.
- `schemas/`: structured alignment, manifest, and report models.
- `i18n/`: JSON translation catalogs and lookup helper.
- `model_registry.py`, `doctor.py`, `device.py`: runtime capability and model
  metadata helpers.

The Worker does not implement a second ASR path. `LYRIC_DRAFT_EXTRACTION`
delegates to `CandidateLyricsExtractionService`, which is also used by
`xingyu-align candidate extract`.

## Worker Protocol Boundary

`schemaVersion: 1` is preserved for v0.3.0 alignment jobs. `schemaVersion: 2`
requires `taskType`. `schemaVersion: 3` adds draft extraction `preset` and
`overrides` while keeping v1/v2 compatibility. Supported task types are:

- `LYRICS_ALIGNMENT`
- `LYRIC_DRAFT_EXTRACTION`

Path validation is intentionally stricter than the general CLI:

- audio must resolve under `--music-dir`;
- lyrics and section manifests must resolve under the current job directory;
- output must be exactly the current job's `result/`;
- symlink and `../` escapes are rejected.

This lets the Worker run inside Docker with `/music` read-only and `/jobs` plus
`/models` writable, without exposing ports or mounting the Docker socket.

`status.json` is the single current-state snapshot and is written atomically.
`events.jsonl` is an append-only lifecycle stream. Stale detection prefers
`status.json.heartbeatAt` and falls back to the legacy `RUNNING` marker mtime
only when status is missing or damaged.

## Local Data Directories

- `/models` or `models/`: model cache and upstream downloads.
- `/jobs`: Worker requests, status files, attempts, intermediates, and results.
- `outputs/`: direct CLI output examples.
- `docs/`: project documentation.
