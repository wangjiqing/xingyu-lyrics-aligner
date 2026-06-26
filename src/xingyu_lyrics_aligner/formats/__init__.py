"""Lyrics format parsers and serializers."""

from xingyu_lyrics_aligner.formats.swlrc import (
    SwlrcDiagnostic,
    SwlrcDocument,
    SwlrcLine,
    SwlrcSyntaxError,
    SwlrcToken,
    SwlrcValidationError,
    SwlrcValidationResult,
    parse_swlrc,
    serialize_swlrc,
    validate_swlrc,
)

__all__ = [
    "SwlrcDiagnostic",
    "SwlrcDocument",
    "SwlrcLine",
    "SwlrcSyntaxError",
    "SwlrcToken",
    "SwlrcValidationError",
    "SwlrcValidationResult",
    "parse_swlrc",
    "serialize_swlrc",
    "validate_swlrc",
]
