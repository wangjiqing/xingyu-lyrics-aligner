# Notes

- ASR text is timing evidence only. Trusted lyrics are never replaced by ASR output.
- Normalization is comparison-only: NFKC, lowercase Latin text, drop punctuation/symbols/whitespace, map Arabic digits to Chinese digit characters, and apply a small ASR confusion fold.
- Greedy matching is useful as a debug baseline but can commit too early around repeated lines or skipped ASR segments.
- Dynamic programming is the preferred coarse locator because it can skip ASR-only material, leave lyrics unmatched, and match one lyric line to multiple ASR segments.
- Window generation is deliberately simple: expand anchors with fixed pre/post roll, widen low-confidence windows, enforce minimum length, and trim adjacent overlap.
- The fixture validates algorithm behavior, not WhisperX ASR quality. Real audio validation should be a separate pass using `--run-whisperx`.
