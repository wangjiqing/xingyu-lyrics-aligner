"""Candidate lyric extraction helpers."""

from xingyu_lyrics_aligner.candidate_lyrics.script_normalization import (
    ScriptNormalizationError,
    convert_chinese_script,
    normalize_transcript_script,
)
from xingyu_lyrics_aligner.candidate_lyrics.transcription import (
    CandidateLyricsError,
    TranscriptionResult,
    TranscriptSegment,
    WordTiming,
    clean_transcript_segments,
    extract_candidate_lyrics,
)

__all__ = [
    "CandidateLyricsError",
    "ScriptNormalizationError",
    "TranscriptSegment",
    "TranscriptionResult",
    "WordTiming",
    "clean_transcript_segments",
    "convert_chinese_script",
    "extract_candidate_lyrics",
    "normalize_transcript_script",
]
