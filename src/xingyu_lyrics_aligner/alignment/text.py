"""Trusted lyric text loading and display/alignment text mapping."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

NOISE_CHARS = set(
    ",.?¿!¡;:\"'‘’“”%~`_+<>=…–—-，。！？、；：（）()[]【】《》〈〉「」『』♪♫♬·・‧～〜〽\\/|^*@#$&"
)


@dataclass(frozen=True)
class TokenSpec:
    """Display token and its length in model-facing alignment characters."""

    text: str
    alignment_text: str

    @property
    def alignment_length(self) -> int:
        return len(self.alignment_text)


@dataclass(frozen=True)
class LineSpec:
    """One trusted lyric line in display and alignment forms."""

    index: int
    text: str
    alignment_text: str
    tokens: list[TokenSpec]


class TrustedLineKind(StrEnum):
    LRC_METADATA = "LRC_METADATA"
    NON_LYRIC_HEADER = "NON_LYRIC_HEADER"
    SINGING_LYRIC = "SINGING_LYRIC"


@dataclass(frozen=True)
class TrustedLyricLine:
    text: str
    kind: TrustedLineKind
    source_line_index: int
    header_kind: str | None = None


@dataclass(frozen=True)
class TrustedLyricsDocument:
    lines: list[TrustedLyricLine]
    warnings: list[str]

    @property
    def singing_lines(self) -> list[TrustedLyricLine]:
        return [line for line in self.lines if line.kind == TrustedLineKind.SINGING_LYRIC]

    @property
    def preserved_header_lines(self) -> list[TrustedLyricLine]:
        return [line for line in self.lines if line.kind != TrustedLineKind.SINGING_LYRIC]


LRC_METADATA_RE = re.compile(r"^\[(ti|ar|al|by|offset)\s*:[^\]]*\]$", re.IGNORECASE)
CREDIT_RE = re.compile(
    r"^\s*(作词|作曲|词曲|编曲|演唱|歌手|混音|混录|音乐总监|监制|制作人|发行|出品|和声|录音|母带)\s*[:：]"
)
SEPARATOR_RE = re.compile(r"^\s*[-—–_=·•─]{2,}\s*$")


def read_lyrics(path: Path) -> list[str]:
    """Read non-empty trusted lyric lines without modifying their display text."""
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    return [line for line in lines if line]


def parse_trusted_lyrics(path: Path) -> TrustedLyricsDocument:
    """Classify leading metadata/credit blocks without guessing inside sung lyrics."""
    raw_lines = [
        (index, line.strip())
        for index, line in enumerate(path.read_text(encoding="utf-8").splitlines())
        if line.strip()
    ]
    kinds: dict[int, tuple[TrustedLineKind, str]] = {}
    warnings: list[str] = []
    for pos, (_, text) in enumerate(raw_lines):
        if LRC_METADATA_RE.fullmatch(text):
            kinds[pos] = (TrustedLineKind.LRC_METADATA, "METADATA")

    # Only a leading, closed separator block containing an explicit credit field is safe.
    non_metadata_positions = [pos for pos in range(len(raw_lines)) if pos not in kinds]
    if non_metadata_positions:
        first = non_metadata_positions[0]
        if SEPARATOR_RE.fullmatch(raw_lines[first][1]):
            closing = next(
                (
                    pos
                    for pos in non_metadata_positions[1:]
                    if SEPARATOR_RE.fullmatch(raw_lines[pos][1])
                ),
                None,
            )
            if closing is not None and any(
                CREDIT_RE.match(raw_lines[pos][1]) for pos in range(first + 1, closing)
            ):
                for pos in range(first, closing + 1):
                    text = raw_lines[pos][1]
                    if SEPARATOR_RE.fullmatch(text):
                        block_kind = "SEPARATOR"
                    elif CREDIT_RE.match(text):
                        block_kind = "CREDIT"
                    else:
                        block_kind = "TITLE"
                    kinds[pos] = (TrustedLineKind.NON_LYRIC_HEADER, block_kind)
            else:
                warnings.append(f"ambiguous_header_format_treated_as_singing:{raw_lines[first][0]}")

    # Also accept consecutive explicit credit fields at the very beginning (after metadata).
    cursor = 0
    while (
        cursor < len(raw_lines)
        and cursor in kinds
        and kinds[cursor][0] == TrustedLineKind.LRC_METADATA
    ):
        cursor += 1
    while cursor < len(raw_lines) and CREDIT_RE.match(raw_lines[cursor][1]):
        kinds[cursor] = (TrustedLineKind.NON_LYRIC_HEADER, "CREDIT")
        cursor += 1

    lines = []
    for pos, (source_index, text) in enumerate(raw_lines):
        classified: tuple[TrustedLineKind, str | None] = kinds.get(
            pos, (TrustedLineKind.SINGING_LYRIC, None)
        )
        kind, header_kind = classified
        lines.append(TrustedLyricLine(text, kind, source_index, header_kind))
    return TrustedLyricsDocument(lines=lines, warnings=warnings)


def clean_alignment_text(text: str) -> str:
    """Build model-facing text without correcting or rewriting user lyrics."""
    normalized = unicodedata.normalize("NFKC", text)
    chars: list[str] = []
    for char in normalized:
        if char.isspace():
            continue
        category = unicodedata.category(char)
        if char in NOISE_CHARS or category.startswith(("P", "S")):
            continue
        chars.append(char)
    return "".join(chars)


def tokenize_display_text(text: str) -> list[str]:
    """Tokenize display text for readable JSON, falling back to characters."""
    try:
        import jieba

        return [token for token in jieba.lcut(text, cut_all=False) if token]
    except Exception:
        return [char for char in text if not char.isspace()]


def build_line_specs(lines: list[str]) -> list[LineSpec]:
    """Create line specs while preserving original display text."""
    specs: list[LineSpec] = []
    for index, line in enumerate(lines):
        tokens = [
            TokenSpec(text=token, alignment_text=clean_alignment_text(token))
            for token in tokenize_display_text(line)
        ]
        specs.append(
            LineSpec(
                index=index,
                text=line,
                alignment_text="".join(token.alignment_text for token in tokens),
                tokens=tokens,
            )
        )
    return specs
