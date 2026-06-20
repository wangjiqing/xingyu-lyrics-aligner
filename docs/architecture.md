# Architecture

Xingyu Lyrics Aligner is designed as a local-first CLI project. The current bootstrap keeps runtime concerns separated so future model integration can be added without changing user-facing contracts.

## Layers

- `cli.py`: Typer commands, option parsing, and human-readable output.
- `i18n/`: JSON translation catalogs and a small lookup helper.
- `device.py`: device strategy names and local capability detection.
- `doctor.py`: structured environment checks. The report is already modeled for future JSON output.
- `model_registry.py`: model slots and local status. v0.1.0 never downloads or loads model files.
- `schemas.py`: Pydantic models for future job manifests, model manifests, alignment results, and export metadata.

## Future Alignment Boundary

Real alignment should be introduced behind an engine interface, for example:

```text
src/xingyu_lyrics_aligner/alignment/
  engine.py
  manifest.py
  exporters/
```

The CLI should build a `JobManifest`, pass it to an alignment service, then export results. The service should return an `AlignmentResult` rather than writing CLI text directly.

## Xingyu Music Library Boundary

Future Xingyu music-library integration should be treated as an input provider. It can supply trusted audio paths, lyrics text, metadata, and hashes, but it should not be mixed with the alignment engine itself.

## Local Data Directories

- `models/`: future local model files and manifests.
- `cache/`: transient processing cache.
- `outputs/`: generated LRC and JSON exports.
- `docs/`: project documentation.
- `src/xingyu_lyrics_aligner/i18n/`: CLI translation resources.

## JSON Output Readiness

`DoctorReport`, `JobManifest`, `AlignmentResult`, and `ExportResult` are Pydantic models so future `--json` output can serialize structured data without scraping human CLI text.
