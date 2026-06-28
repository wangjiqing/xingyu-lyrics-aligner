# Xingyu Lyrics Aligner

[English](README.md) | [简体中文](README.zh-CN.md)

Xingyu Lyrics Aligner is a local-first trusted-lyrics alignment CLI. v0.2.0
aligns a local audio file against user-provided lyric lines, defines SWLRC v1,
and adds optional ASR candidate-lyrics extraction for manual review.

The recommended user command is:

```bash
xingyu-align
```

`xingyu-lyrics-aligner` is kept as a compatibility alias. `python -m
xingyu_lyrics_aligner.cli` is only intended for development and troubleshooting.

## What v0.2.0 Can Do

- Read a local audio file and a trusted line-by-line lyrics text file.
- Build Chinese CTC alignment text without rewriting the display lyrics.
- Run WhisperX CTC forced alignment without ASR transcription.
- Export `alignment.json`, `lyrics.lrc`, `lyrics.swlrc`, and `report.json`.
- Optionally use a manual section manifest for structure-aware alignment.
- Define and validate SWLRC v1, an enhanced character-/word-level timed lyrics
  format for Xingyu Audio Library and Xingyu Music Box.
- Optionally extract ASR candidate lyrics from audio through Demucs vocals
  separation plus faster-whisper, for manual review only.
- Generate Simplified or Traditional Chinese review copies of candidate lyrics
  without overwriting the original ASR output.

## Boundaries And Known Limits

- ASR transcription is available only through the explicit `candidate extract`
  workflow and is not part of trusted alignment by default.
- The CLI does not fetch public lyrics, rewrite user lyrics, or upload audio.
- Demucs is used only by the optional candidate-lyrics workflow. UVR, GUI,
  database, and Web services are out of scope for v0.2.0.
- macOS MPS may fall back to CPU for WhisperX alignment.
- Windows CUDA is not covered by the macOS installer.
- LRC display timing can vary by player because each player decides how to render
  line transitions.
- SWLRC token timing quality depends on the upstream alignment result. Missing
  token timings may be estimated from the containing line, and untimed lines are
  skipped with warnings in `report.json`.
- Complex spoken parts, overlapping foreground voices, and manual section
  boundaries still need review. Watch for `foreground_voice_switch` and
  `section_boundary_review` warnings.
- Vocal separation is not part of the trusted alignment flow.
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

Install directly from the GitHub v0.2.0 tag:

```bash
curl -fsSL https://raw.githubusercontent.com/wangjiqing/xingyu-lyrics-aligner/v0.2.0/scripts/install-macos.sh | bash -s -- --source github --ref v0.2.0
```

Include optional candidate-lyrics dependencies:

```bash
curl -fsSL https://raw.githubusercontent.com/wangjiqing/xingyu-lyrics-aligner/v0.2.0/scripts/install-macos.sh | bash -s -- --source github --ref v0.2.0 --candidate-lyrics
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
xingyu-align help
xingyu-align align -h
```

For model, cache, config, and launcher path details, see
[Runtime Environment](docs/runtime-environment.md).

You can change the saved CLI language later:

```bash
xingyu-align config set-locale zh-CN
xingyu-align config show
```

Update from GitHub:

```bash
xingyu-align update --run
xingyu-align update --candidate-lyrics --ref v0.2.0 --run
```

## Manual Development Install

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev,alignment]"
```

Developer fallback:

```bash
python -m xingyu_lyrics_aligner.cli -h
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

By default this writes:

```text
alignment.json
lyrics.lrc
lyrics.swlrc
report.json
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

For a machine-readable local invocation, use `--json-result`. stdout will contain
one JSON object; human-facing messages and errors are written to stderr.

```bash
xingyu-align align \
  --audio "/music/song.flac" \
  --lyrics "/workspace/song.lrc" \
  --output-dir "/workspace/alignment-result" \
  --language zh \
  --device cpu \
  --json-result
```

The success payload includes `success`, `output_dir`, `files`, `summary`, and
`warnings`. On failure the process exits non-zero and stdout still contains a
parseable JSON object with `success: false` and an `error` object.

## Candidate Lyrics Command

Candidate lyrics are optional ASR output for review. Install candidate
dependencies first:

```bash
python -m pip install -e ".[candidate-lyrics]"
```

Extract candidate lyrics:

```bash
xingyu-align candidate extract \
  --audio "/path/to/song.flac" \
  --output-dir "/path/to/prelyrics" \
  --language zh \
  --model medium
```

This writes `vocals.wav`, `transcript.raw.txt`, `transcript.segments.json`,
`transcript.cleaned.txt`, and `report.json`. Use `--skip-separation` to skip
Demucs and transcribe the original mix directly.

Generate Simplified or Traditional Chinese review copies:

```bash
xingyu-align candidate normalize \
  --input "/path/to/prelyrics/transcript.cleaned.txt" \
  --output-dir "/path/to/prelyrics" \
  --to zh-Hans

xingyu-align candidate normalize \
  --input "/path/to/prelyrics/transcript.cleaned.txt" \
  --output-dir "/path/to/prelyrics" \
  --to zh-Hant
```

These copies are for manual review, online lyric comparison, and alignment
preparation. They are not trusted lyrics.

## Output Files

- `alignment.json`: the core timeline for future character highlighting. It
  preserves trusted lyric display text and token timestamps.
- `lyrics.lrc`: standard line-level LRC export. `--lrc-offset-ms` only affects
  this file.
- `lyrics.swlrc`: SWLRC v1 export for character-/word-level highlighting. It
  uses absolute times and always writes `[swlrc:1]`, `[offset:0]`, and
  `[tokenization:...]`. `--lrc-offset-ms` is not applied to SWLRC.
- `report.json`: compact statistics, warnings, model, and device information. It
  does not copy the full lyrics. SWLRC export warnings and estimated/skipped
  counts are included here.

## SWLRC

SWLRC (`.swlrc`) is an enhanced character- and word-level timed lyrics format
defined and emitted by Xingyu Lyrics Aligner for Xingyu Audio Library and Xingyu
Music Box. The v1 specification lives in
[docs/specs/swlrc-v1.md](docs/specs/swlrc-v1.md), with readable examples under
[docs/examples](docs/examples).

Chinese output defaults to `tokenization:char`; Chinese word tokens from the
alignment result are split into character tokens for playback highlighting. For
English and other non-Chinese lyrics, existing word-level tokens are preserved
when present. If token times are missing but the line has a valid time range,
the exporter estimates token ranges inside that line and records the count. If a
line has no valid time range, it is skipped rather than fabricating legal times.

## Python API

```python
from xingyu_lyrics_aligner import align_lyrics

result = align_lyrics(
    audio_path="/music/song.flac",
    lyrics_path="/workspace/song.lrc",
    output_dir="/workspace/alignment-result",
    language="zh",
    device="cpu",
)

print(result.files["swlrc"])
```

The returned object contains structured documents, output paths, and SWLRC
export statistics. Xingyu Audio Library should prefer the CLI with
`--json-result` for phase-one process isolation, and can later call this API
directly without importing internal modules.

## Candidate Lyrics

The `xingyu-align candidate` commands can generate ASR candidate lyrics from
local audio for manual review. They do not replace trusted lyrics and do not
produce SWLRC. See
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
