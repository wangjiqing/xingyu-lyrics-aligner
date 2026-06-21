"""Quality summary helpers for alignment outputs."""

from __future__ import annotations

from xingyu_lyrics_aligner.alignment.backmap import CharacterTiming
from xingyu_lyrics_aligner.alignment.text import LineSpec
from xingyu_lyrics_aligner.schemas.alignment import AlignmentLine


def count_non_monotonic(lines: list[AlignmentLine]) -> int:
    """Count lines whose start time moves backwards."""
    count = 0
    previous: float | None = None
    for line in lines:
        if line.start is None:
            continue
        if previous is not None and line.start < previous:
            count += 1
        end = line.end if line.end is not None else line.start
        previous = max(previous if previous is not None else end, end)
    return count


def status_counts(lines: list[AlignmentLine]) -> dict[str, int]:
    """Return status histogram using public string values."""
    counts: dict[str, int] = {}
    for line in lines:
        counts[line.status.value] = counts.get(line.status.value, 0) + 1
    return counts


def timed_character_count(chars: list[CharacterTiming]) -> int:
    """Count characters with both start and end timestamps."""
    return sum(1 for char in chars if char.start is not None and char.end is not None)


def input_character_count(line_specs: list[LineSpec]) -> int:
    """Count model-facing alignment characters."""
    return sum(len(line.alignment_text) for line in line_specs)
