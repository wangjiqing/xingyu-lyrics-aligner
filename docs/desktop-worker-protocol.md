# Desktop Worker Protocol

`DESKTOP_LYRIC_PROCESSING` is the schema version 3 task for one complete
trusted-lyrics Desktop operation. It does not run ASR and does not replace the
existing `LYRICS_ALIGNMENT` or `LYRIC_DRAFT_EXTRACTION` task types.

## Request

Create `/jobs/{jobId}/request.json`, then atomically create the `READY` marker:

```json
{
  "schemaVersion": 3,
  "taskType": "DESKTOP_LYRIC_PROCESSING",
  "jobId": "desktop-001",
  "audioPath": "/music/song.flac",
  "trustedLyricsPath": "/jobs/desktop-001/trusted-lyrics.txt",
  "outputDir": "/jobs/desktop-001/result",
  "language": "zh",
  "device": "cpu",
  "exports": {
    "lrc": true,
    "swlrc": true,
    "vocals": false,
    "accompaniment": false,
    "alignmentJson": false,
    "reportJson": false
  }
}
```

All paths remain absolute Worker paths. `audioPath` must resolve under
`--music-dir`; `trustedLyricsPath` must resolve inside this job directory; and
`outputDir` must be exactly this job's `result` directory. Unknown fields are
rejected. At least one of `exports.lrc` and `exports.swlrc` must be true.

LRC and SWLRC default to true. The other export flags default to false. Selecting
neither audio track skips Demucs. Selecting either `vocals` or `accompaniment`
runs Demucs exactly once; the task never invokes faster-whisper or any other ASR.

## Formal artifacts

A successful or `NEEDS_REVIEW` result keeps the existing `result.files` mapping
and also includes an independently versioned contract:

```json
{
  "artifactsSchemaVersion": 1,
  "artifacts": [
    {
      "id": "lyrics.lrc",
      "kind": "LRC",
      "relativePath": "result/lyrics.lrc",
      "mediaType": "text/plain",
      "exportable": true,
      "temporary": false
    }
  ]
}
```

Supported kinds are `LRC`, `SWLRC`, `ALIGNMENT_JSON`, `REPORT_JSON`, `VOCALS`,
and `ACCOMPANIMENT`. Every entry is added only after the file exists and resolves
inside the job directory. Absolute paths and `..` traversal are invalid.

Audio exports have stable product paths:

```text
result/audio/vocals.wav
result/audio/accompaniment.wav
```

Demucs' `_demucs/<model>/<track>/` directory and its `no_vocals.wav` name are
private implementation details. The Worker removes the Desktop intermediate
directory after success, cancellation, or failure without removing formal
result files.

## State, stages, and progress

The Desktop task reports only observed call boundaries:

```text
VALIDATING_REQUEST
PREPARING_AUDIO
SEPARATING_VOCALS       # only when an audio track was selected
LOADING_ALIGNMENT_MODEL
ALIGNING
EXPORTING_OUTPUTS
QUALITY_CHECKING
FINALIZING
```

Each stage change atomically refreshes `status.json` and appends a
`STAGE_STARTED` event. Report warnings also append `WARNING` events. Running
progress remains `INDETERMINATE`; terminal progress is `COMPLETE`. No percentage
or remaining-time estimate is synthesized.

Schema version 3 status snapshots include truthful runtime identity:

```json
{
  "runtime": {
    "workerVersion": "0.7.0",
    "pythonVersion": "3.11.15",
    "platform": "Darwin-arm64"
  }
}
```

Values are read from the installed package and current Python/platform at run
time; the example values are illustrative.

## Cooperative cancellation

Create `/jobs/{jobId}/CANCEL_REQUESTED` to request cancellation. The Desktop
task checks it before validation, before separation, after separation/before
alignment, at alignment stage boundaries, and before formal output writing.
When observed, the Worker:

- removes Desktop intermediate files;
- writes atomic status with state `CANCELLED` and no error;
- creates the `CANCELLED` terminal marker;
- appends `TASK_CANCELLED`;
- does not create `SUCCEEDED`, `NEEDS_REVIEW`, or `FAILED`.

Cancellation is cooperative: a blocking Demucs or model call finishes or
returns to the next boundary first. Once formal export starts, the Worker
finishes its verified result and terminal commit instead of creating an
uncontracted partial result. `RUNNING` remains as historical claim evidence in
all terminal states, matching existing Worker behavior; clients use
`status.json.state` as authoritative.

If formal artifact verification fails after that commit boundary, the task is
`FAILED` even if `CANCEL_REQUESTED` arrives concurrently. A cancellation that
arrives after verification or during quality checking does not override the
verified `SUCCEEDED`/`NEEDS_REVIEW` terminal result.

The Worker does not currently install a SIGTERM handler. A Desktop app should
write `CANCEL_REQUESTED` and allow a boundary to complete before terminating the
process. Forced termination can later be classified as `ABANDONED` through the
existing heartbeat timeout; SIGTERM-to-CANCELLED conversion remains future work.

## Compatibility

Schema versions 1, 2, and 3 remain accepted. Existing request fields, CLI
output, `result.files`, marker behavior, and the alignment/draft task dispatch
are unchanged. New runtime metadata is additive for schema version 3. The
artifacts v1 contract is currently emitted by `DESKTOP_LYRIC_PROCESSING`; older
task results retain their prior shapes.
