# Notes

- This spike tests direct trusted-lyrics CTC alignment as the primary path.
- It deliberately does not run WhisperX transcription.
- ASR/DP coarse localization is out of the happy path and remains a future fallback/diagnostic tool.
- The first phase uses original FLAC audio directly. Demucs/vocal separation is optional and not a prerequisite for this spike.
- Real-song outputs belong under ignored `local_output/` and must not be committed.

