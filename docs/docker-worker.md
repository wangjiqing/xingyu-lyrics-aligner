# Docker Worker Protocol

v0.4.0 extends the shared-directory Worker with candidate lyric draft
extraction. The Worker remains a local executor: it exposes no HTTP port, uses
no database or message queue, and does not need the Docker socket.

## Mounted Paths

```text
/music   read-only audio library
/jobs    requests, status, attempt logs, and outputs
/models  writable persistent model cache
```

The container runs as UID/GID `10001:10001`. The host `/jobs` and `/models`
directories must be writable by that user, or the Compose service must set a
compatible `user:`. `/music` should be mounted read-only.

The v0.4.0 standard image installs both alignment and candidate-lyrics
dependencies, including faster-whisper, Demucs, TorchCodec, and their runtime
dependencies. It is larger than v0.3.0. First use may download or warm model
files into `/models`, and CPU draft extraction is much slower and uses more
temporary disk than trusted-lyrics alignment.

The Dockerfile finishes by reinstalling the CPU PyTorch runtime from the PyTorch
CPU wheel index: `torch==2.11.0+cpu`, `torchaudio==2.11.0+cpu`,
`torchvision==0.26.0+cpu`, and `torchcodec==0.14.0+cpu`. This is required so
TorchCodec can load in the slim CPU image. WhisperX 3.8.6 still declares
`torch~=2.8.0`, so Docker build logs may include a resolver warning; release
smoke tests must verify `import whisperx` and `import torchcodec` in the final
image.

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

`status.json` is always machine-readable JSON. It is written to a temporary file
in the same directory, flushed, fsynced, and atomically renamed into place.
Readers should accept additional fields.

Running status includes both the older `status` field and the v0.4.0 `state`
field:

```json
{
  "schemaVersion": 2,
  "jobId": "job-001",
  "taskType": "LYRIC_DRAFT_EXTRACTION",
  "status": "RUNNING",
  "state": "RUNNING",
  "stage": "transcribing",
  "progress": null,
  "startedAt": "2026-07-04T00:00:00Z",
  "updatedAt": "2026-07-04T00:00:00Z",
  "warningCount": 0,
  "errorMessage": null
}
```

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
are kept.

Stale `RUNNING` jobs are marked `ABANDONED` after
`--running-timeout-seconds`. They are not retried automatically; the caller
should create a new job directory if a retry is desired.

## Compose And Regression

Start from [deploy/docker-compose.worker.example.yml](../deploy/docker-compose.worker.example.yml)
and [deploy/.env.worker.example](../deploy/.env.worker.example).

```bash
docker build -t wangjiqing/xingyu-lyrics-aligner:0.4.0 .

docker run --rm \
  --user 10001:10001 \
  -v "$PWD/music:/music:ro" \
  -v "$PWD/alignment-jobs:/jobs" \
  -v "$PWD/aligner-model-cache:/models" \
  wangjiqing/xingyu-lyrics-aligner:0.4.0 \
  xingyu-align worker run --jobs-dir /jobs --music-dir /music --device cpu --once
```

Do not publish ports and do not mount `/var/run/docker.sock`. GPU containers
are not part of the v0.4.0 contract; validate PyTorch, WhisperX, faster-whisper,
Demucs, CUDA runtime, and host drivers separately before publishing a GPU
profile.
