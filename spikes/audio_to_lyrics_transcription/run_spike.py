#!/usr/bin/env python3
"""Compatibility wrapper for the promoted candidate-lyrics extraction script."""

from __future__ import annotations

from xingyu_lyrics_aligner.candidate_lyrics.transcription import main

if __name__ == "__main__":
    raise SystemExit(main())
