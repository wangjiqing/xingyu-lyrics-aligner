# Direct Trusted Lyrics CTC Alignment Spike

This is an independent technical spike for the revised v0.1.1 direction. It does not change the main CLI.

Primary path under test:

```text
local audio
+ trusted Chinese lyric lines
-> display text + alignment text
-> one global WhisperX CTC alignment segment, or optional manual sections
-> character timestamps
-> backfill to original lines and display tokens
-> local LRC + JSON + review warnings
```

ASR transcription is intentionally not part of the default path.

## Safety

Do not commit:

- real audio;
- real lyrics;
- complete LRC;
- full alignment JSON;
- ASR output;
- token timelines from commercial songs;
- model files, stems, or caches.

Real validation output goes to ignored `local_output/`.
Real section manifests go to ignored `local_input/`.

## Setup

The script uses the same WhisperX family validated by the previous spike:

```bash
cd spikes/direct_trusted_lyrics_ctc_alignment
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If the previous spike virtual environment exists, it can also be reused for local validation.

## Run

Original version:

```bash
python run_spike.py \
  --audio "/Users/wangjiqing/Documents/Music/郑源 - 曾经爱过你.flac" \
  --lyrics "/Users/wangjiqing/Documents/Music/郑源 - 曾经爱过你.txt" \
  --output-dir local_output/zhengyuan \
  --device cpu \
  --language zh \
  --model-cache-only \
  --foreground-voice-switch-lines 1-4
```

K-song version:

```bash
python run_spike.py \
  --audio "/Users/wangjiqing/Documents/Music/星语 - 曾经爱过你.flac" \
  --lyrics "/Users/wangjiqing/Documents/Music/星语 - 曾经爱过你.txt" \
  --output-dir local_output/xingyu \
  --device cpu \
  --language zh \
  --model-cache-only
```

Adjust `--foreground-voice-switch-lines` after inspecting the local lyrics file. The argument is 1-based and accepts comma-separated numbers/ranges, for example `3,5-7`.

## Manual Section Mode

Section mode is an optional experiment for structure-aware CTC alignment. It does not
use ASR or DP matching. Each section sends only its own trusted lyric lines to
WhisperX alignment, bounded by the manually supplied audio interval.

```bash
python run_spike.py \
  --audio "/absolute/path/song.flac" \
  --lyrics "/absolute/path/song.txt" \
  --output-dir local_output/song_sectional \
  --device cpu \
  --language zh \
  --model-cache-only \
  --section-manifest local_input/song.sections.json
```

Manifest convention:

- `line_start` is 0-based and inclusive.
- `line_end` is 0-based and exclusive.
- `audio_start` and `audio_end` are seconds on the full-song timeline.
- Section outputs are written back as absolute full-song timestamps.
- Sections may contain small audio padding, but lyric line ranges must not overlap.
- `kind: "foreground_voice_switch"` marks all lines in that section for manual review.

See `section_manifest.example.json` for a fictional schema example. Do not commit
real song boundaries if they are part of local validation material.

## Outputs

The script writes full outputs only to the selected ignored directory:

- `alignment.raw.json`
- `alignment.normalized.json`
- `sample.lrc`
- `simple.lrc`
- `summary.json`
- `report.md`
- `section_report.md`

Only aggregate summary values should be copied into discussions or committed documents.
