"""Trusted lyric text loading and display/alignment text mapping."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
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


def read_lyrics(path: Path) -> list[str]:
    """Read non-empty trusted lyric lines without modifying their display text."""
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    return [line for line in lines if line]


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
