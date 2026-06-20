# Xingyu Lyrics Aligner

[English](README.md) | [简体中文](README.zh-CN.md)

Xingyu Lyrics Aligner is a local-first lyrics forced-alignment toolkit bootstrap. Users will provide an audio file and trusted lyrics text; future versions can align the lyrics to the audio and export line-level LRC plus word-level or character-level JSON timelines.

The v0.1.0 scope is intentionally small: it creates the Python project foundation, CLI shape, i18n structure, device checks, data models, and documentation boundaries. It does not perform real model inference.

## Current Scope

Included in v0.1.0:

- Python `src/` layout with `pyproject.toml`.
- Typer CLI entrypoint: `xingyu-align`.
- Commands: `doctor`, `models list`, `models status`, and `align`.
- Minimal `en-US` and `zh-CN` CLI text resources.
- Device strategy definitions: `auto`, `cpu`, `cuda`, and `mps`.
- Pydantic schemas for future job manifests, model manifests, alignment results, and exports.
- Smoke tests and baseline lint, format, and type-check configuration.

Not included in v0.1.0:

- Whisper transcription or automatic lyric recognition.
- Vocal separation.
- Real forced alignment.
- Model downloads or bundled model weights.
- Database, Web UI, or desktop UI.

## Install for Development

Python `>=3.11,<3.14` is used to keep a modern language baseline while staying conservative for future PyTorch packaging on macOS Apple Silicon, Windows CUDA, and CPU environments.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

## CLI Preview

```bash
xingyu-align doctor
xingyu-align models list
xingyu-align models status
xingyu-align align --audio song.wav --lyrics lyrics.txt --device auto --language zh-CN
```

`align` validates inputs only. It will not fabricate an alignment result.

Locale can be selected with either:

```bash
XINGYU_ALIGN_LOCALE=zh-CN xingyu-align doctor
xingyu-align --locale zh-CN doctor
```

## Planned Inputs and Outputs

Planned input:

- A local audio file.
- Trusted lyrics text supplied by the user or a future Xingyu music-library boundary.
- Optional device and language hints.

Planned output:

- Line-level LRC.
- Internal JSON with line-level, word-level, and character-level mappings.
- Confidence and review status fields for human correction workflows.
- Job manifests containing audio hash, lyrics hash, device, model version, language, alignment mode, and created time.

## Local-First Principle

Audio and lyrics should be processed locally by default. The project must not upload audio to third-party APIs as part of the core alignment workflow.

## License

Apache-2.0. See [LICENSE](LICENSE).

## Development Checks

```bash
ruff format .
ruff check .
mypy
pytest
```
