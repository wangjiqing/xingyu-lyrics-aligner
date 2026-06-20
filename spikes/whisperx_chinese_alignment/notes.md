# Notes

- WhisperX 3.8.6 exposes alignment as `whisperx.align(segments, model_a, metadata, audio, device, return_char_alignments=True)`.
- The alignment API needs pre-windowed segments containing `start`, `end`, and `text`.
- Therefore WhisperX is not a direct whole-song "trusted lyrics plus audio" forced aligner. A product implementation must first create reliable line windows, then call alignment on trusted text.
- Chinese `zh` defaults to the Hugging Face CTC model `jonatasgrosman/wav2vec2-large-xlsr-53-chinese-zh-cn`.
- The tested Chinese model produced usable Chinese character timings when the trusted lyric text was inserted into segments.
- ASR baseline recognized the synthetic text incorrectly (`星语` as `新鱼`, `流淌` as `流逃`) and merged all text into one segment. ASR can help find coarse speech windows, but must not become lyric truth.
- MPS failed in this environment before inference. CPU alignment completed.
