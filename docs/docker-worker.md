# Docker Worker Protocol

v0.3.0 adds an optional shared-directory Worker for Docker Compose deployments.
It is a local executor, not a service platform: it does not expose HTTP ports,
does not use a database, does not use a message queue, and does not need the
Docker socket.

## Mounted Paths

```text
/music   read-only audio library
/jobs    alignment requests and outputs
/models  persistent model cache
```

The container runs as UID/GID `10001:10001`. The host `/jobs` and `/models`
directories must be writable by that user, or the Compose service must set a
compatible `user:`. `/music` should be read-only.

For the default UID/GID:

```bash
mkdir -p alignment-jobs aligner-model-cache
sudo chown -R 10001:10001 alignment-jobs aligner-model-cache
```

## Job Layout

```text
/jobs/{jobId}/
  request.json
  trusted-lyrics.txt
  sections.json
  READY
  RUNNING
  ABANDONED
  status.json
  stderr.log
  result/
    alignment.json
    lyrics.lrc
    lyrics.swlrc
    report.json
```

`sections.json` is optional. `READY`, `RUNNING`, and `ABANDONED` are marker
files; a normal completed job keeps `RUNNING` as evidence that the Worker
claimed it. Claiming is done by exclusive `RUNNING` file creation, followed by
removing `READY`; two Workers cannot both create the same `RUNNING` marker.

## request.json

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

Path rules are enforced before alignment:

- `audioPath` must be absolute and stay under `/music`.
- `lyricsPath`, `sectionManifestPath`, and `outputDir` must be absolute and stay
  under `/jobs`.
- `../` escapes and symlink-resolved escapes are rejected.

## Status Contract

`status.json` is always machine-readable JSON. It is written to a temporary file
in the same directory, flushed, fsynced, and atomically renamed into place so the
caller does not observe partial JSON. While running:

```json
{
  "schemaVersion": 1,
  "jobId": "job-001",
  "status": "RUNNING",
  "updatedAt": "2026-06-28T00:00:00Z"
}
```

Successful alignment writes the same payload shape as `xingyu-align align
--json-result` under `result`:

```json
{
  "schemaVersion": 1,
  "jobId": "job-001",
  "status": "SUCCEEDED",
  "updatedAt": "2026-06-28T00:00:00Z",
  "attempt": {
    "id": "20260628T000000Z-12345",
    "stderr": "/jobs/job-001/attempts/20260628T000000Z-12345.stderr.log"
  },
  "result": {
    "success": true,
    "output_dir": "/jobs/job-001/result",
    "files": {
      "alignment_json": "/jobs/job-001/result/alignment.json",
      "lrc": "/jobs/job-001/result/lyrics.lrc",
      "swlrc": "/jobs/job-001/result/lyrics.swlrc",
      "report": "/jobs/job-001/result/report.json"
    },
    "summary": {
      "line_count": 1,
      "aligned_line_count": 1,
      "token_count": 1,
      "coverage": 1.0,
      "estimated_token_count": 0,
      "skipped_line_count": 0
    },
    "warnings": []
  }
}
```

Before writing `SUCCEEDED` or `NEEDS_REVIEW`, the Worker verifies that
`alignment.json`, `lyrics.lrc`, `lyrics.swlrc`, and `report.json` all exist. A
missing required output is `FAILED` with `OUTPUT_MISSING`.

`NEEDS_REVIEW` is used when alignment exits successfully but quality signals need
human review: non-empty warnings, skipped SWLRC lines, coverage below
`--min-coverage`, or estimated token count above
`--estimated-token-review-threshold`.

Failures keep tracebacks in `attempts/{attemptId}.stderr.log`, refresh
`stderr.log` as the latest-attempt convenience copy, and write a structured
summary. A retry can overwrite `stderr.log`, but previous attempt logs are kept.

```json
{
  "schemaVersion": 1,
  "jobId": "job-001",
  "status": "FAILED",
  "updatedAt": "2026-06-28T00:00:00Z",
  "attempt": {
    "id": "20260628T000000Z-12345",
    "stderr": "/jobs/job-001/attempts/20260628T000000Z-12345.stderr.log"
  },
  "error": {
    "code": "PATH_OUTSIDE_ALLOWED_ROOT",
    "message": "audioPath must stay under /music: /tmp/song.flac",
    "stderr": "/jobs/job-001/stderr.log",
    "attemptStderr": "/jobs/job-001/attempts/20260628T000000Z-12345.stderr.log"
  }
}
```

Stale `RUNNING` jobs are marked `ABANDONED` after
`--running-timeout-seconds`. They are not retried automatically in v0.3.0; the
caller should create a new job directory if a retry is desired.

## Compose

Start from [deploy/docker-compose.worker.example.yml](../deploy/docker-compose.worker.example.yml)
and [deploy/.env.worker.example](../deploy/.env.worker.example). Preheat models
first:

```bash
mkdir -p alignment-jobs aligner-model-cache
sudo chown -R 10001:10001 alignment-jobs aligner-model-cache

docker compose --env-file deploy/.env.worker.example \
  -f deploy/docker-compose.worker.example.yml run --rm \
  xingyu-lyrics-aligner-worker \
  xingyu-align models pull --language zh --device cpu
```

GPU containers are not part of the v0.3.0 contract. Future GPU support should be
validated separately for PyTorch, WhisperX, CUDA runtime, and host drivers before
publishing a GPU Compose profile.
