# macOS Desktop Development

For the standalone candidate build, see [macOS bundled runtime](macos-runtime.md)
and [release candidate](macos-release.md). Debug continues to prefer the
development runtime; Release prefers `Contents/Resources/runtime/bin/python3`.

The v0.7.0 Desktop MVP is a native SwiftUI application for Apple Silicon and
macOS 14 or later. Debug can use the repository Worker. Release candidates
embed Python and FFmpeg but not model weights, use ad-hoc signing, and are not
Developer ID signed or notarized.

## Prepare the Python runtime

From the repository root, install the alignment runtime into `.venv` using the
existing project instructions. A typical source checkout uses:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -e ".[dev,alignment,candidate-lyrics]"
.venv/bin/xingyu-align doctor
.venv/bin/python -m xingyu_lyrics_aligner.cli desktop readiness --json
```

FFmpeg and FFprobe must be available in the Debug development PATH. The bundled
Release uses its own verified binaries. The app lets the user explicitly
install pinned alignment and optional separation weights and never starts a
download during launch.

Runtime lookup order is:

1. executable path in `XINGYU_ALIGNER_PYTHON`;
2. `<XINGYU_ALIGNER_REPOSITORY_ROOT>/.venv/bin/python` when that optional root is set;
3. `.venv/bin/python` found by walking up from the process working directory or app bundle.

It never silently falls back to a system Python. The selected executable is
shown in the UI. To set an explicit runtime in the Xcode scheme environment:

```text
XINGYU_ALIGNER_PYTHON=/absolute/path/to/xingyu-lyrics-aligner/.venv/bin/python
```

On launch, structured readiness checks gate task execution. A missing separation
model blocks only vocals/accompaniment jobs. See
[macOS Desktop Model Management](macos-model-management.md) for model metadata,
install events, licenses, managed directories, and cleanup.

## Open, build, and test

Open:

```text
apps/macos/XingyuLyricsAligner.xcodeproj
```

Select the shared `XingyuLyricsAligner` scheme and run on My Mac. The scheme's
development working directory is the repository root.

Command-line build and tests:

```bash
xcodebuild \
  -project apps/macos/XingyuLyricsAligner.xcodeproj \
  -scheme XingyuLyricsAligner \
  -configuration Debug \
  -destination 'platform=macOS,arch=arm64' \
  CODE_SIGNING_ALLOWED=NO \
  build

xcodebuild \
  -project apps/macos/XingyuLyricsAligner.xcodeproj \
  -scheme XingyuLyricsAligner \
  -destination 'platform=macOS,arch=arm64' \
  CODE_SIGNING_ALLOWED=NO \
  test
```

## Development task data

The app copies input files and creates schema v3 jobs under:

```text
~/Library/Application Support/XingyuLyricsAligner/Development/
├── Jobs/<jobId>/
└── Music/<jobId>/
```

The Worker is launched once per song with the selected Python, without a shell:

```text
python -m xingyu_lyrics_aligner.cli worker run --once
  --jobs-dir <Development/Jobs>
  --music-dir <Development/Music>
  --device cpu
```

The app passes its Application Support cache and model environment explicitly to
both installer and Worker processes. `XINGYU_APP_SUPPORT_DIR` selects a disposable
root for development tests; otherwise Application Support is used.

The default export destination is:

```text
~/Music/Xingyu Lyrics Aligner/<source audio name>/
```

The song subdirectory uses stable names such as `lyrics.lrc`, `lyrics.swlrc`,
`vocals.wav`, and `accompaniment.wav`. The UI states that a new run replaces
those known same-name outputs in that song directory.

To remove development task data after the app and Worker have exited, delete the
`Development` directory shown above. User-selected export directories are not
part of this cleanup.

## Current limitations

- Apple Silicon only; Intel is not configured.
- No App Sandbox or security-scoped bookmarks.
- The DMG candidate is ad-hoc signed only, without Developer ID or notarization.
- Debug uses external Python/FFmpeg; Release embeds them. Models use App-managed
  Application Support directories and are not embedded in the app bundle.
- The Demucs checkpoint and optional Demucs Python package are independent; both
  are required for dual-track jobs.
- Cancellation is cooperative at Worker stage boundaries. Force terminate is
  reserved for app shutdown and results in the existing abandoned-job semantics.
- Progress is intentionally indeterminate unless the Worker reports truthful
  numeric progress.
- Single-song processing only; no playback, waveform, history, batch jobs, ASR
  drafts, or online lyrics.
