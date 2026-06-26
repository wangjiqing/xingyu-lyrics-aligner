# Xingyu Lyrics Aligner

[English](README.md) | [简体中文](README.zh-CN.md)

Xingyu Lyrics Aligner is a local-first trusted-lyrics alignment CLI. v0.1.1 aligns
a local audio file against user-provided lyric lines and exports a compact JSON
timeline plus a standard line-level LRC file.

The recommended user command is:

```bash
xingyu-align
```

`xingyu-lyrics-aligner` is kept as a compatibility alias. `python -m
xingyu_lyrics_aligner.cli` is only intended for development and troubleshooting.

## What v0.1.1 Can Do

- Read a local audio file and a trusted line-by-line lyrics text file.
- Build Chinese CTC alignment text without rewriting the display lyrics.
- Run WhisperX CTC forced alignment without ASR transcription.
- Export `alignment.json`, `lyrics.lrc`, and `report.json`.
- Optionally use a manual section manifest for structure-aware alignment.

## Boundaries And Known Limits

- ASR transcription is not the default path.
- The CLI does not fetch public lyrics, rewrite user lyrics, or upload audio.
- Demucs, UVR, GUI, database, and Web services are out of scope for v0.1.1.
- macOS MPS may fall back to CPU for WhisperX alignment.
- Windows CUDA is not covered by the macOS installer.
- LRC display timing can vary by player because each player decides how to render
  line transitions.
- Complex spoken parts, overlapping foreground voices, and manual section
  boundaries still need review. Watch for `foreground_voice_switch` and
  `section_boundary_review` warnings.
- Vocal separation is not a v0.1.1 default capability.
- Real audio, lyrics, LRC, JSON timelines, and model caches should not be committed.

## macOS Quick Install

This installer supports source checkouts on macOS Apple Silicon / CPU routes. It
does not install Homebrew, does not edit shell config, and does not download
models automatically.

```bash
git clone https://github.com/wangjiqing/xingyu-lyrics-aligner.git
cd xingyu-lyrics-aligner
./scripts/install-macos.sh
```

To choose and save the default CLI language during install:

```bash
./scripts/install-macos.sh --locale zh-CN
```

If `ffmpeg` is missing, install it yourself:

```bash
brew install ffmpeg
```

If `~/.local/bin` is not on `PATH`, the installer prints the exact zsh command:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

After installation:

```bash
xingyu-align doctor
xingyu-align models pull --language zh
xingyu-align align --help
```

For model, cache, config, and launcher path details, see
[Runtime Environment](docs/runtime-environment.md).

You can change the saved CLI language later:

```bash
xingyu-align config set-locale zh-CN
xingyu-align config show
```

## Manual Development Install

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev,alignment]"
```

Developer fallback:

```bash
python -m xingyu_lyrics_aligner.cli --help
```

## Doctor

```bash
xingyu-align doctor
```

Checks Python, OS, CPU/GPU capability hints, and `ffmpeg`.

## Model Download

Check local model status:

```bash
xingyu-align models status --language zh
```

Explicitly download/preheat the Chinese alignment model:

```bash
xingyu-align models pull --language zh
```

`pull` prints the model name, source, and size notice before download. It does
not run ASR transcription and does not generate song outputs.

## Minimal Alignment Command

```bash
xingyu-align align \
  --audio "/path/to/song.flac" \
  --lyrics "/path/to/song.txt" \
  --output-dir "/path/to/output" \
  --language zh
```

With a manual section manifest:

```bash
xingyu-align align \
  --audio "/path/to/song.flac" \
  --lyrics "/path/to/song.txt" \
  --output-dir "/path/to/output" \
  --language zh \
  --section-manifest "/path/to/song.sections.json"
```

Write real outputs outside the repository or under ignored directories such as
`local_output/`.

## Output Files

- `alignment.json`: the core timeline for future character highlighting. It
  preserves trusted lyric display text and token timestamps.
- `lyrics.lrc`: standard line-level LRC export. `--lrc-offset-ms` only affects
  this file.
- `report.json`: compact statistics, warnings, model, and device information. It
  does not copy the full lyrics.

## SWLRC

SWLRC (`.swlrc`) is an enhanced character- and word-level timed lyrics format
defined and emitted by Xingyu Lyrics Aligner for Xingyu Audio Library and Xingyu
Music Box. The v1 specification lives in
[docs/specs/swlrc-v1.md](docs/specs/swlrc-v1.md), with readable examples under
[docs/examples](docs/examples).

## Candidate Lyrics

Optional scripts can generate ASR candidate lyrics from local audio for manual
review. They do not replace trusted lyrics and do not produce SWLRC. See
[Candidate Lyrics](docs/guides/candidate-lyrics.md).

## Run From Any Directory

The macOS installer creates:

```text
~/.local/bin/xingyu-align
```

It points to this checkout's `.venv`, so you can run:

```bash
cd /tmp
xingyu-align --help
```

## FAQ

### `xingyu-align: command not found`

Make sure `~/.local/bin` is on `PATH`:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

### `ffmpeg` is missing

Install it manually:

```bash
brew install ffmpeg
```

### Model Not Prepared

Run:

```bash
xingyu-align models pull --language zh
```

### MPS Falls Back To CPU

This is expected for the current WhisperX CTC alignment route on macOS. The
result metadata records the requested and actual alignment device.

### Output Already Exists

Use a new output directory or pass:

```bash
--overwrite
```

### Git Safety

Do not commit real audio, trusted lyric files, generated LRC, full JSON
timelines, model caches, stems, or `local_output/`.

## Development Checks

```bash
ruff check .
pytest
bash -n scripts/install-macos.sh
```

## License

Apache-2.0. See [LICENSE](LICENSE).
