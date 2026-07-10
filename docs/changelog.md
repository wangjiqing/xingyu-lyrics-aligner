# Changelog

See [../CHANGELOG.md](../CHANGELOG.md) for the release history.

## 0.6.0 Header Preservation

- `NON_LYRIC_HEADER` content does not consume CTC characters or section lyric indices.
- Alignment/report/CLI/Worker results expose preserved lines and display-only intro hints.
- SWLRC v1 remains a singing-token-only timeline.

## 0.4.0 Worker Draft Extraction

- Adds Worker `schemaVersion: 2` with explicit `taskType`.
- Supports `LYRICS_ALIGNMENT` and `LYRIC_DRAFT_EXTRACTION`.
- Keeps `schemaVersion: 1` compatible with v0.3.0 alignment jobs.
- Reuses the candidate lyric extraction service for Worker draft tasks.
- Writes draft outputs to `/jobs/{jobId}/result`:
  `transcript.cleaned.txt`, `transcript.raw.txt`,
  `transcript.segments.json`, and `report.json`.
- Cleans `intermediate/vocals.wav` by default; keeps it only when
  `retainIntermediate` is true.
- Updates the standard Docker image to include alignment and candidate-lyrics
  dependencies.
