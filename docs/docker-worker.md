# Docker Worker Protocol

v0.5.0 makes the shared-directory Worker observable while preserving candidate
lyric draft extraction from v0.4.0. The Worker remains a local executor: it
exposes no HTTP port, uses no database or message queue, and does not need the
Docker socket.

## Mounted Paths

```text
/music   read-only audio library
/jobs    requests, status, attempt logs, and outputs
/models  writable persistent model cache
```

The container runs as UID/GID `10001:10001`. The host `/jobs` and `/models`
directories must be writable by that user, or the Compose service must set a
compatible `user:`. `/music` should be mounted read-only.

The v0.5.0 standard image installs both alignment and candidate-lyrics
dependencies, including faster-whisper, Demucs, TorchCodec, and their runtime
dependencies. It is larger than v0.3.0. First use may download or warm model
files into `/models`, and CPU draft extraction is much slower and uses more
temporary disk than trusted-lyrics alignment.

The Dockerfile finishes by reinstalling the CPU PyTorch runtime from the PyTorch
CPU wheel index: `torch==2.11.0+cpu`, `torchaudio==2.11.0+cpu`,
`torchvision==0.26.0+cpu`, and `torchcodec==0.14.0+cpu`. This is required so
TorchCodec can load in the slim CPU image. The reinstall uses a `--no-deps`
runtime override. Project extras do not directly pin TorchCodec; the standard
Docker image owns that runtime choice, and release smoke tests must verify
`import whisperx` and `import torchcodec` in the final image.

## Job Layout

Alignment jobs:

```text
/jobs/{jobId}/
  request.json
  trusted-lyrics.txt
  sections.json
  READY
  RUNNING
  SUCCEEDED | NEEDS_REVIEW | FAILED | ABANDONED
  status.json
  events.jsonl
  stderr.log
  attempts/
  result/
    alignment.json
    lyrics.lrc
    lyrics.swlrc
    report.json
```

Candidate lyric draft extraction jobs:

```text
/jobs/{jobId}/
  request.json
  READY
  RUNNING
  SUCCEEDED | FAILED | ABANDONED
  status.json
  events.jsonl
  stderr.log
  attempts/
  intermediate/
    vocals.wav
  result/
    transcript.cleaned.txt
    transcript.raw.txt
    transcript.segments.json
    report.json
```

`sections.json` is optional for alignment. `intermediate/vocals.wav` is kept
only when the request sets `retainIntermediate: true`; otherwise the Worker
cleans it after success or failure. Draft extraction never writes
`NEEDS_REVIEW`, because all candidate lyrics require human correction before
they can become trusted lyrics.

Claiming is done by exclusive `RUNNING` file creation, followed by removing
`READY`. Two Workers cannot both create the same `RUNNING` marker. Completed
jobs keep `RUNNING` as claim evidence and also receive a terminal marker.

## Request Protocol

### schemaVersion 1

Schema v1 is the v0.3.0 alignment protocol and remains supported. It is always
treated as `LYRICS_ALIGNMENT`; adding `taskType` to v1 is rejected by the
existing `extra=forbid` rule.

```json
{
  "schemaVersion": 1,
  "jobId": "job-001",
  "audioPath": "/music/artist/song.flac",
  "lyricsPath": "/jobs/job-001/trusted-lyrics.txt",
  "outputDir": "/jobs/job-001/result",
  "language": "zh",
  "device": "cpu",
  "sectionManifestPath": null,
  "createdAt": "2026-06-28T00:00:00Z"
}
```

### schemaVersion 2 Alignment

Schema v2 requires `taskType`. Alignment v2 keeps the same output contract as
v1.

```json
{
  "schemaVersion": 2,
  "jobId": "job-001",
  "taskType": "LYRICS_ALIGNMENT",
  "audioPath": "/music/artist/song.flac",
  "lyricsPath": "/jobs/job-001/trusted-lyrics.txt",
  "outputDir": "/jobs/job-001/result",
  "language": "zh",
  "device": "cpu",
  "sectionManifestPath": null,
  "createdAt": "2026-07-04T00:00:00Z"
}
```

### schemaVersion 2 Draft Extraction

Draft extraction converts audio into unaligned ASR candidate text for manual
editing. It does not produce LRC, SWLRC, or trusted lyrics.

```json
{
  "schemaVersion": 2,
  "jobId": "job-001",
  "taskType": "LYRIC_DRAFT_EXTRACTION",
  "audioPath": "/music/artist/song.flac",
  "outputDir": "/jobs/job-001/result",
  "language": "zh",
  "device": "cpu",
  "asrModel": "medium",
  "skipSeparation": false,
  "vadFilter": true,
  "conditionOnPreviousText": false,
  "keepSuspectedMetadata": false,
  "retainIntermediate": false,
  "createdAt": "2026-07-04T00:00:00Z"
}
```

### schemaVersion 3 Draft Extraction

Schema v3 keeps v1/v2 compatibility and adds a preset plus explicit advanced
overrides for `LYRIC_DRAFT_EXTRACTION`. Unknown fields, invalid presets, and
invalid override value types fail before execution with stable error codes.
See also [worker-draft-request-v3.json](examples/worker-draft-request-v3.json).

```json
{
  "schemaVersion": 3,
  "jobId": "job-001",
  "taskType": "LYRIC_DRAFT_EXTRACTION",
  "audioPath": "/music/artist/song.flac",
  "outputDir": "/jobs/job-001/result",
  "language": "zh",
  "device": "cpu",
  "preset": "RECOMMENDED",
  "overrides": {
    "asrModel": "large-v3",
    "skipSeparation": false,
    "vadFilter": false
  },
  "createdAt": "2026-07-08T00:00:00Z"
}
```

Preset defaults:

| Preset | ASR model | Vocal separation | VAD |
| --- | --- | --- | --- |
| `FAST` | `small` | skipped | enabled |
| `RECOMMENDED` | `medium` | skipped | enabled |
| `HIGH_QUALITY` | `medium` | enabled | enabled |
| `FULL_RECOGNITION` | `medium` | enabled | disabled |

Resolution order is preset defaults, then explicit user overrides, then Worker
runtime constraints such as the `--device` override. The Worker writes both
`requestedConfig` and `resolvedConfig` to `status.json`; candidate draft
`report.json` also records the same resolved execution choices. v1/v2 draft
requests without a preset keep the old equivalent behavior: `medium`, vocal
separation enabled, VAD enabled. `large-v3` remains an advanced override; it is
slower and heavier, so it is not part of the normal presets.

## Path Rules

The Worker validates paths after claiming and before execution:

- `jobId` must exactly match the current job directory name.
- `audioPath` must be an existing file under `--music-dir`.
- `lyricsPath` and `sectionManifestPath` must be existing files under the
  current job directory.
- `outputDir` must be exactly `/jobs/{jobId}/result`.
- All request paths must be absolute.
- `../` escapes and symlink-resolved escapes are rejected.
- Unknown request fields are rejected.

These rules prevent a request from reading arbitrary host files or writing
outside the current job directory.

## Status Contract

`status.json` is the only authoritative current-state snapshot. There is no
separate `progress.json`. The file is always machine-readable JSON and is
written to a temporary file in the same directory, flushed, fsynced, and
atomically renamed into place. Readers should accept additional fields.

Running status includes both the older `status` field and the v0.5.0 `state`
field for compatibility:

```json
{
  "statusSchemaVersion": 1,
  "requestSchemaVersion": 3,
  "schemaVersion": 2,
  "jobId": "job-001",
  "taskType": "LYRIC_DRAFT_EXTRACTION",
  "status": "RUNNING",
  "state": "RUNNING",
  "stage": "TRANSCRIBING",
  "startedAt": "2026-07-08T10:00:00Z",
  "stageStartedAt": "2026-07-08T10:03:10Z",
  "updatedAt": "2026-07-08T10:04:25Z",
  "heartbeatAt": "2026-07-08T10:04:25Z",
  "progress": {
    "kind": "INDETERMINATE",
    "current": null,
    "total": null,
    "fraction": null
  },
  "attempt": {
    "id": "20260708T100000Z-10001-123456789",
    "number": 1,
    "stderrPath": "attempts/20260708T100000Z-10001-123456789.stderr.log"
  },
  "requestedConfig": {
    "preset": "RECOMMENDED"
  },
  "resolvedConfig": {
    "preset": "RECOMMENDED",
    "asrModel": "medium",
    "skipSeparation": true,
    "vadFilter": true,
    "device": "cpu",
    "language": "zh"
  },
  "warnings": [],
  "warningCount": 0,
  "errorMessage": null,
  "error": null,
  "result": null
}
```

Time semantics:

- `startedAt` is when the current attempt started; stage changes do not refresh
  it.
- `stageStartedAt` changes only when `stage` changes.
- `updatedAt` is the last status write time.
- `heartbeatAt` is the last time the Worker confirmed the attempt was alive.

Stable states are `QUEUED` for callers before `READY`, then Worker-written
`RUNNING`, `SUCCEEDED`, `NEEDS_REVIEW`, `FAILED`, and `ABANDONED`. The Worker
defines `QUEUED` for the shared protocol but does not write it itself; an upper
system may write `QUEUED` before creating `READY`. Current Worker stages are
machine codes, not localized text:

- Alignment: `VALIDATING_REQUEST`, `PREPARING_INPUT`,
  `LOADING_ALIGNMENT_MODEL`, `PREPARING_ALIGNMENT_TEXT`, `ALIGNING`,
  `EXPORTING_OUTPUTS`, `QUALITY_CHECKING`, `FINALIZING`.
- Draft extraction: `VALIDATING_REQUEST`, `PREPARING_AUDIO`,
  `SEPARATING_VOCALS`, `LOADING_ASR_MODEL`, `TRANSCRIBING`,
  `POSTPROCESSING_TRANSCRIPT`, `WRITING_OUTPUTS`, `FINALIZING`.

The implementation uses the subset it can observe safely. `DOWNLOADING_MODEL`
is intentionally absent until the Worker can distinguish download from slow
model loading. Progress is `INDETERMINATE` unless a backend provides truthful
progress; v0.5.0 does not hard-code fake 20/50/80 percent values.

`events.jsonl` is an append-only lifecycle event stream. Each line is an
independent JSON object:

```json
{"eventId":"20260708T100425Z-0001","timestamp":"2026-07-08T10:04:25Z","level":"INFO","type":"STAGE_STARTED","stage":"TRANSCRIBING","message":"Started stage TRANSCRIBING.","details":{"model":"medium","vadFilter":true}}
```

Readers should ignore an incomplete final line. Event types are stable:
`TASK_ACCEPTED`, `STAGE_STARTED`, `STAGE_PROGRESS`, `WARNING`,
`TASK_COMPLETED`, `TASK_NEEDS_REVIEW`, `TASK_FAILED`, and `TASK_ABANDONED`.
Events are not a stderr replacement; keep reading `stderr.log` or the attempt
stderr for diagnostics.

Example files:

- [worker-status-running-v1.json](examples/worker-status-running-v1.json)
- [worker-events.jsonl](examples/worker-events.jsonl)

Alignment success writes the same payload shape as `xingyu-align align
--json-result` under `result` and verifies `alignment.json`, `lyrics.lrc`,
`lyrics.swlrc`, and `report.json` before `SUCCEEDED` or `NEEDS_REVIEW`.

Draft extraction success verifies these files before `SUCCEEDED`:

```text
result/transcript.cleaned.txt
result/transcript.raw.txt
result/transcript.segments.json
result/report.json
```

`report.json` includes at least `taskType`, ASR model, separation and VAD
settings, duration, output summary, warnings, and errors. Paths under
`report.outputs` are container paths such as `/jobs/job-001/result/...`; map them
through the host volume mount when reading files outside the container.

Failures keep tracebacks in `attempts/{attemptId}.stderr.log`, refresh
`stderr.log` as the latest-attempt convenience copy, and write structured
failure status. A retry can overwrite `stderr.log`, but previous attempt logs
are kept. The user-facing `error.message` is a short stable summary, not a raw
Python traceback.

```json
{
  "code": "ASR_TRANSCRIPTION_FAILED",
  "message": "ASR transcription failed while processing the audio.",
  "retryable": false,
  "suggestedAction": "Inspect the source audio or try a different extraction preset.",
  "stderrPath": "stderr.log",
  "attemptStderrPath": "attempts/attempt-id.stderr.log"
}
```

Current stable error code domains include request validation
(`REQUEST_INVALID`, `REQUEST_INVALID_JSON`, `TASK_TYPE_MISSING`,
`UNKNOWN_TASK_TYPE`, `UNSUPPORTED_SCHEMA`, `INVALID_PRESET`), path validation
(`PATH_NOT_ABSOLUTE`, `PATH_MISSING`, `PATH_NOT_FILE`,
`PATH_OUTSIDE_ALLOWED_ROOT`, `OUTPUT_DIR_INVALID`), runtime failures
(`MODEL_LOAD_FAILED`, `MODEL_NOT_AVAILABLE`, `VOCAL_SEPARATION_FAILED`,
`ASR_TRANSCRIPTION_FAILED`, `ALIGNMENT_FAILED`, `OUTPUT_WRITE_FAILED`,
`OUTPUT_MISSING`, `QUALITY_CHECK_FAILED`, `INTERNAL_ERROR`), and lifecycle
timeouts (`RUNNING_TIMEOUT`).

Stale `RUNNING` jobs are marked `ABANDONED` after
`--running-timeout-seconds`. The check first uses `status.json.heartbeatAt`; the
older `RUNNING` marker mtime is only a compatibility fallback for missing or
damaged status files. A long model call with a fresh heartbeat is considered
alive. Abandoned jobs are not retried automatically; the caller should create a
new job directory if a retry is desired.

## Compose And Regression

Start from [deploy/docker-compose.worker.example.yml](../deploy/docker-compose.worker.example.yml)
and [deploy/.env.worker.example](../deploy/.env.worker.example).

```bash
docker build -t wangjiqing/xingyu-lyrics-aligner:0.5.0 .

docker run --rm \
  --user 10001:10001 \
  -v "$PWD/music:/music:ro" \
  -v "$PWD/alignment-jobs:/jobs" \
  -v "$PWD/aligner-model-cache:/models" \
  wangjiqing/xingyu-lyrics-aligner:0.5.0 \
  xingyu-align worker run --jobs-dir /jobs --music-dir /music --device cpu --once
```

Do not publish ports and do not mount `/var/run/docker.sock`. GPU containers
are not part of the v0.5.0 contract; validate PyTorch, WhisperX, faster-whisper,
Demucs, CUDA runtime, and host drivers separately before publishing a GPU
profile.
