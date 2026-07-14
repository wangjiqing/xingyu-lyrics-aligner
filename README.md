# Xingyu Lyrics Aligner

[English](README.md) | [简体中文](README.zh-CN.md)

Xingyu Lyrics Aligner is a local-first trusted-lyrics alignment tool. v0.7.0
aligns local audio against user-provided lyric lines, defines SWLRC v1, keeps
optional ASR candidate-lyrics extraction for manual review, and adds an official
CPU Docker image plus an optional shared-directory Worker for Docker Compose
integrations. The Worker can also extract unaligned candidate lyric drafts from
audio for later human correction, while exposing stable status, stage,
heartbeat, event, configuration, result, and error snapshots for upper systems.

The recommended user command is:

```bash
xingyu-align
```

`xingyu-lyrics-aligner` is kept as a compatibility alias. `python -m
xingyu_lyrics_aligner.cli` is only intended for development and troubleshooting.

## What v0.7.0 Can Do

- Read a local audio file and a trusted line-by-line lyrics text file.
- Build Chinese CTC alignment text without rewriting the display lyrics.
- Run WhisperX CTC forced alignment without ASR transcription.
- Export `alignment.json`, `lyrics.lrc`, `lyrics.swlrc`, and `report.json`.

### Preserved credits and intro display (v0.6.0)

Standard LRC metadata and conservatively recognized leading credit blocks are classified before
CTC. `NON_LYRIC_HEADER` lines do not consume alignment characters or section lyric indices. Their
original text and order are retained in LRC and structured results; they are never SWLRC tokens.

Results add `firstAlignedLyricStartMs`, `preservedHeaderLines`, and optional
`presentationHints`. Suggested ranges are display-only, bounded by the first aligned lyric, and
are not part of the lyric timeline. Existing consumers may ignore these additive fields.
- Optionally use a manual section manifest for structure-aware alignment.
- Run the same CLI inside the official CPU Docker image.
- Optionally run `xingyu-align worker run` against a mounted `/jobs` directory
  for Xingyu Audio Library Docker Compose deployments.
- Let the Worker process `LYRIC_DRAFT_EXTRACTION` jobs that turn audio into
  unaligned candidate lyric drafts for manual editing.
- Expose Worker state through `/jobs/{jobId}/status.json` and lifecycle events
  through `/jobs/{jobId}/events.jsonl`.
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
  database, HTTP services, message queues, and Docker socket access are out of
  scope for v0.5.0.
- The default CLI path does not start a long-running process. The Docker Worker
  is an optional deployment adapter for shared-directory integrations.
- macOS MPS may fall back to CPU for WhisperX alignment.
- Windows CUDA is not covered by the macOS installer.

The native SwiftUI macOS Desktop MVP is implemented under [`apps/macos`](apps/macos)
for Apple Silicon and macOS 14+. The v0.7.0 development branch can build an
unsigned DMG candidate with bundled Python/FFmpeg, local readiness, explicit
model installation, trusted-lyrics processing, optional two-track separation,
and artifact export. Audio stays local and model weights are downloaded
separately into Application Support. This is not a published GitHub Release and
has no Developer ID signature or notarization. See
[`docs/macos-unsigned-install.md`](docs/macos-unsigned-install.md),
[`docs/macos-runtime.md`](docs/macos-runtime.md), and
[`docs/macos-model-management.md`](docs/macos-model-management.md).
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

Install directly from the GitHub v0.6.1 tag:

```bash
curl -fsSL https://raw.githubusercontent.com/wangjiqing/xingyu-lyrics-aligner/v0.6.1/scripts/install-macos.sh | bash -s -- --source github --ref v0.6.1
```

Include optional candidate-lyrics dependencies:

```bash
curl -fsSL https://raw.githubusercontent.com/wangjiqing/xingyu-lyrics-aligner/v0.6.1/scripts/install-macos.sh | bash -s -- --source github --ref v0.6.1 --candidate-lyrics
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
xingyu-align update --candidate-lyrics --ref v0.6.1 --run
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

## Docker CLI

The official CPU image is published at:

```text
ghcr.io/wangjiqing/xingyu-lyrics-aligner
docker.io/<DOCKERHUB_USERNAME>/xingyu-lyrics-aligner
```

GHCR is the primary example registry in this README. Release tags are mirrored to
Docker Hub with the same version tags: `0.6.1`, `0.6`, `latest`, and `v0.6.1`.
Images are published for `linux/amd64` and `linux/arm64`; Apple Silicon Macs pull
the ARM64 image by default.

Run doctor:

```bash
docker run --rm \
  -v /host/music:/music:ro \
  -v /host/jobs:/jobs \
  -v /host/models:/models \
  ghcr.io/wangjiqing/xingyu-lyrics-aligner:v0.6.1 \
  xingyu-align doctor
```

Preheat the Chinese alignment model into the mounted cache:

```bash
docker run --rm \
  -v /host/music:/music:ro \
  -v /host/jobs:/jobs \
  -v /host/models:/models \
  ghcr.io/wangjiqing/xingyu-lyrics-aligner:v0.6.1 \
  xingyu-align models pull --language zh --device cpu
```

Run one alignment:

```bash
docker run --rm \
  -v /host/music:/music:ro \
  -v /host/jobs:/jobs \
  -v /host/models:/models \
  ghcr.io/wangjiqing/xingyu-lyrics-aligner:v0.6.1 \
  xingyu-align align \
    --audio /music/song.flac \
    --lyrics /jobs/job-001/trusted-lyrics.txt \
    --output-dir /jobs/job-001/result \
    --language zh \
    --device cpu \
    --json-result
```

The image runs as non-root UID/GID `10001:10001`. Mount `/music` read-only, keep
`/jobs` and `/models` writable, and persist `/models` to avoid re-downloading
model files. The image does not download models at build time.

```bash
mkdir -p alignment-jobs aligner-model-cache
sudo chown -R 10001:10001 alignment-jobs aligner-model-cache
```

## Docker Worker

The schema v3 `DESKTOP_LYRIC_PROCESSING` task provides one-shot trusted-lyrics
alignment, optional two-track export, formal artifacts, and cooperative
cancellation. See [Desktop Worker Protocol](docs/desktop-worker-protocol.md).

For Xingyu Audio Library Docker Compose deployments, the optional Worker can poll
a shared jobs directory. v0.5.0 supports two task types:

- `LYRICS_ALIGNMENT`: trusted lyrics + audio -> `alignment.json`, LRC, SWLRC.
- `LYRIC_DRAFT_EXTRACTION`: audio -> unaligned ASR candidate lyric text for
  manual correction. This output is not trusted lyrics.

```bash
xingyu-align worker run --jobs-dir /jobs --music-dir /music --device cpu
```

Schema v1 requests remain alignment jobs. Schema v2 requests remain supported.
Schema v3 adds draft-extraction `preset` and `overrides`. The Worker claims jobs
by exclusively creating `RUNNING`, then removing `READY`; writes `status.json`
via temp file plus flush, fsync, and atomic rename; appends `events.jsonl`;
keeps per-attempt stderr logs; and writes terminal markers such as `SUCCEEDED`,
`FAILED`, `NEEDS_REVIEW`, or `ABANDONED`. Draft extraction never writes
`NEEDS_REVIEW`; manual lyric review belongs to the audio-library workflow.

`status.json` is the only current-state snapshot. It includes stable fields such
as `statusSchemaVersion`, `requestSchemaVersion`, `state`, `stage`, `startedAt`,
`stageStartedAt`, `updatedAt`, `heartbeatAt`, `requestedConfig`,
`resolvedConfig`, `warnings`, `error`, and `result`. `events.jsonl` is an
append-only lifecycle stream for state transitions and warnings; it is not a
replacement for `stderr.log` or `attempts/{attemptId}.stderr.log`. Slow jobs
should be treated as alive while `heartbeatAt` is fresh. The Worker does not
invent percentage progress when the underlying model cannot report it safely.

Draft extraction writes `transcript.cleaned.txt`, `transcript.raw.txt`,
`transcript.segments.json`, and `report.json` under `/jobs/{jobId}/result`.
By default, Worker vocals intermediates are cleaned after the attempt. With
`retainIntermediate: true`, `vocals.wav` is kept under
`/jobs/{jobId}/intermediate`, never under `result`.

The Worker only reads `/music` paths and writes `/jobs` and `/models` paths. It
is not an HTTP service, opens no ports, uses no database or message queue, and
does not mount `/var/run/docker.sock`. The v0.6.1 image installs alignment and
candidate-lyrics dependencies, including faster-whisper, Demucs, and TorchCodec,
so it is larger than v0.3.0. First use may download or warm models; CPU draft
extraction is much slower and uses more temporary disk than alignment. See
[Docker Worker](docs/docker-worker.md) and
[deploy/docker-compose.worker.example.yml](deploy/docker-compose.worker.example.yml).

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
  --preset recommended
```

This writes `vocals.wav`, `transcript.raw.txt`, `transcript.segments.json`,
`transcript.cleaned.txt`, and `report.json`. Use `--skip-separation` to skip
Demucs and transcribe the original mix directly.

Draft extraction presets are `fast`, `recommended`, `high-quality`, and
`full-recognition`. `fast` uses a smaller ASR model and skips separation;
`recommended` uses `medium`, skips separation, and keeps VAD on; `high-quality`
uses `medium` with vocal separation; `full-recognition` keeps separation but
disables VAD to avoid filtering weak vocals, speech, or non-standard fragments.
`full-recognition` is not an absolute "most accurate" mode. Advanced options
such as `--model large-v3`, `--skip-separation`, and `--no-vad` override the
preset. `large-v3` remains available as an advanced model name, but it is not in
the normal presets because it is slower and uses more memory and disk.

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
mypy
pytest
bash -n scripts/install-macos.sh
docker build -t xingyu-lyrics-aligner:local .
```

## License

Apache-2.0. See [LICENSE](LICENSE).
