# Roadmap

## v0.1.0 Bootstrap

- Establish Python package structure and CLI entrypoint.
- Add `doctor`, model inspection placeholders, and input validation.
- Add minimal English and Simplified Chinese CLI text resources.
- Define future data models and local directory conventions.

## v0.2.x Planning

- Add stable job manifest read/write.
- Add JSON output mode for `doctor`, `models status`, and dry-run alignment requests.
- Add file hashing utilities for audio and lyrics.
- Define an alignment engine interface without binding to a specific model.
- Add LRC and timeline JSON exporters using synthetic fixture data only.

## Future Model Integration

- Evaluate forced-alignment engines with compatible licenses.
- Keep optional vocal separation behind a separate module and dependency extra.
- Support `auto`, `cpu`, `cuda`, and `mps` routing through one device policy layer.
- Add clear model installation documentation before enabling any model-backed command.

## Non-Goals

- No Whisper automatic transcription in this project scope.
- No third-party API audio upload in the core local workflow.
- No database, Web UI, or desktop UI in the bootstrap phase.
