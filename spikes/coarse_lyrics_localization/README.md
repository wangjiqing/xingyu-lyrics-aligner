# Coarse Lyrics Localization Spike

This is a v0.1.1-pre technical spike. It does not modify the main CLI and does not implement product behavior.

The goal is to test whether local ASR output can be used only as timing evidence while trusted lyric lines remain authoritative. The output windows are intended to feed a later WhisperX character-level alignment step.

## Setup

The default fixture path uses only the Python standard library:

```bash
cd spikes/coarse_lyrics_localization
python3.11 run_spike.py
```

Optional real WhisperX ASR uses the isolated dependency file:

```bash
cd spikes/coarse_lyrics_localization
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python run_spike.py --run-whisperx --audio sample_input/sample.wav --lyrics sample_input/sample_lyrics.txt --device cpu --compute-type int8 --language zh
```

Generated audio, model caches, and virtual environments are ignored.

## Fixture Scenario

The committed ASR fixture intentionally includes non-ideal cases:

- ASR wrong characters: `星语` recognized as `新鱼`, `流淌` as `流逃`.
- Repeated chorus lines.
- A long interlude ASR filler segment.
- One lyric line split across two ASR segments.
- One shortened ASR line.
- One trusted lyric line with no ASR evidence.

This makes the spike deterministic and keeps model/runtime noise out of the coarse-localization algorithm test.

## Outputs

Running `run_spike.py` writes:

- `sample_output/asr.raw.json`
- `sample_output/lyrics.normalized.json`
- `sample_output/localization.raw.json`
- `sample_output/localization.normalized.json`
- `sample_output/report.md`

`localization.normalized.json` uses the dynamic-programming result as the preferred output.

## Current Conclusion

`GO WITH CONSTRAINTS`: DP-based coarse localization is viable as a separate boundary before WhisperX character-level refinement, but it must surface low-confidence, unmatched, and repeated-line cases for review.
