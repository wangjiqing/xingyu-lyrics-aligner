# Coarse Lyrics Localization Spike Report

## 1. Environment

- Date: 2026-06-20
- Platform: `macOS-26.5.1-arm64-arm-64bit` / `arm64`
- Python: `3.11.15`
- FFmpeg: `/opt/homebrew/bin/ffmpeg`
- WhisperX: `unknown`
- PyTorch: `2.8.0`
- Requested device: `cpu`
- CUDA available: `False`
- MPS available: `False`

## 2. Models

- ASR engine: `whisperx-fixture`
- ASR model: `tiny`
- Language: `zh`
- Alignment model: not invoked by this spike. The previous WhisperX spike validated `jonatasgrosman/wav2vec2-large-xlsr-53-chinese-zh-cn` for later character-level refinement.

## 3. Test Audio

- Fixture audio name: `sample.wav`
- Duration used for window clamping: `31.0s`
- The committed sample uses a small ASR fixture shaped like WhisperX output. Generated audio remains ignored. This isolates coarse localization behavior from model download and ASR nondeterminism.

## 4. Test Lyrics

The lyrics contain repeated chorus lines, ASR-like wrong characters, a long interlude, one line split across two ASR segments, one shortened ASR segment, and one intentionally missing sung line.

## 5. Text Normalization

Comparison-only normalization:

- Unicode NFKC to handle full-width/half-width forms.
- Lowercase Latin text.
- Remove Unicode punctuation, symbols, and whitespace.
- Map Arabic digits to Chinese digits for rough numeric comparison.
- Fold a tiny ASR confusion table for matching only, for example `新/星`, `鱼/语`, and `逃/淌`.

The original trusted lyric text is preserved and is never overwritten by ASR text.

## 6. Greedy Strategy

The greedy matcher walks lyric lines in order. For each line it scans the remaining ASR segments, considers one- or two-segment spans, chooses the highest fuzzy score, then advances the ASR cursor past that span.

Result summary:

```json
{
  "status_counts": {
    "matched": 5,
    "low_confidence": 1,
    "unmatched": 1
  },
  "average_score": 0.8257
}
```

Greedy is simple and monotonic, so it avoids matching later lyric lines to earlier ASR segments. Its weakness is local commitment: once it consumes a mediocre repeated-chorus candidate, later lines cannot repair that choice.

## 7. Dynamic Programming Strategy

The DP matcher builds an ordered path across lyric lines and ASR segment spans. It can:

- match a lyric line to a one- or two-segment ASR span;
- skip ASR-only material such as interlude filler;
- skip a lyric line when no adequate ASR anchor exists;
- penalize low-confidence matches.

Cost model:

- match reward = fuzzy score;
- skip ASR penalty = `0.04`;
- skip lyric penalty = `0.72`;
- low confidence penalty = `0.16`;
- candidate rejected below score `0.48`;
- line is low confidence below score `0.82`.

Result summary:

```json
{
  "status_counts": {
    "matched": 5,
    "low_confidence": 1,
    "unmatched": 1
  },
  "average_score": 0.8257
}
```

DP is more suitable for full songs because it optimizes the whole monotonic path. That matters when repeated chorus lines, missing ASR chunks, or interludes would otherwise cause a local greedy choice to shift the rest of the song.

## 8. Window Expansion

For matched anchors:

```text
window_start = max(0, anchor_start - pre_roll - low_confidence_extra)
window_end = min(audio_duration, anchor_end + post_roll + low_confidence_extra)
```

Parameters:

- pre-roll: `0.75s`
- post-roll: `0.9s`
- low-confidence extra: `0.55s`
- minimum window: `1.5s`

Overlapping adjacent windows are trimmed at the midpoint between the neighboring anchors. Low-confidence matches receive wider windows.

## 9. Failure Cases Observed

- ASR wrong characters: `新鱼` still matched trusted `星语`; `流逃` still matched trusted `流淌` via comparison-only confusion folding.
- Repeated chorus: three occurrences of `星语在夜里发光` stayed in chronological order and were flagged as repeats.
- Long interlude: ASR-only `啦` was skipped by DP rather than matched to a lyric line.
- Split line: `把每个字轻轻照亮` matched across two ASR segments.
- Shortened ASR: `明天继续唱` produced a lower score for trusted `明天还会继续唱`, requiring review.
- Missing sung line: `这一句没有唱出声` remained unmatched instead of forcing a bad window.

## 10. JSON Sample

```json
{
  "index": 0,
  "text": "星语在夜里发光",
  "normalized_text": "星语在夜里发光",
  "match_key": "星语在夜里发光",
  "window_start": 4.27,
  "window_end": 7.115,
  "anchor_start": 5.02,
  "anchor_end": 7.05,
  "match_score": 1.0,
  "status": "matched",
  "asr_evidence": [
    {
      "text": "新鱼在夜里发光",
      "start": 5.02,
      "end": 7.05
    }
  ],
  "warnings": [
    "asr_text_differs_from_trusted_lyrics",
    "repeat_occurrence_1_of_3",
    "window_overlap_trimmed"
  ]
}
```

## 11. macOS CPU

The fixture localization path is pure Python and completed locally on macOS CPU in milliseconds. Optional WhisperX ASR remains CPU-runnable according to the prior spike, but it is not the reliability source for lyrics text.

## 12. Windows CUDA

Windows CUDA was not verified in this spike. CUDA should only affect optional ASR runtime, not the deterministic localization algorithm. A Windows validation pass should run WhisperX ASR with `--device cuda --compute-type float16` and then compare the same JSON outputs.

## 13. Recommendation

Conclusion: GO WITH CONSTRAINTS.

The approach is promising enough for v0.1.1 pre-implementation: ASR can provide rough time anchors while trusted lyrics remain authoritative. However, formal implementation must keep the coarse locator as a separate boundary before WhisperX character refinement, and all low-confidence or unmatched lines must be surfaced for review.

Recommended architecture boundary:

1. ASR adapter: local audio to raw timed ASR segments.
2. Text normalizer: comparison-only forms, never mutating trusted lyrics.
3. Coarse locator: DP-first line-to-ASR path with greedy/debug fallback.
4. Window builder: expands and trims anchor windows.
5. Fine aligner: WhisperX character-level alignment inside each trusted window.
6. Review layer: exposes low-confidence, unmatched, and repeated-line warnings.
