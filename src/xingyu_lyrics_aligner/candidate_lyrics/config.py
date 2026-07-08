"""Shared candidate lyric draft extraction configuration resolver."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class DraftExtractionPreset(StrEnum):
    """Stable preset names for ASR candidate lyric draft extraction."""

    FAST = "FAST"
    RECOMMENDED = "RECOMMENDED"
    HIGH_QUALITY = "HIGH_QUALITY"
    FULL_RECOGNITION = "FULL_RECOGNITION"


@dataclass(frozen=True)
class DraftExtractionConfig:
    """Resolved execution configuration for candidate lyric extraction."""

    preset: str | None
    asr_model: str
    skip_separation: bool
    vad_filter: bool
    condition_on_previous_text: bool
    keep_suspected_metadata: bool
    retain_intermediate: bool

    def to_worker_json(self) -> dict[str, object]:
        return {
            "preset": self.preset,
            "asrModel": self.asr_model,
            "skipSeparation": self.skip_separation,
            "vadFilter": self.vad_filter,
            "conditionOnPreviousText": self.condition_on_previous_text,
            "keepSuspectedMetadata": self.keep_suspected_metadata,
            "retainIntermediate": self.retain_intermediate,
        }

    def to_report_json(self) -> dict[str, object]:
        return {
            "preset": self.preset,
            "asr_model": self.asr_model,
            "skip_separation": self.skip_separation,
            "vad_filter": self.vad_filter,
            "condition_on_previous_text": self.condition_on_previous_text,
            "keep_suspected_metadata": self.keep_suspected_metadata,
            "retain_intermediate": self.retain_intermediate,
        }


class DraftConfigError(ValueError):
    """Stable resolver error that can be mapped to Worker error codes."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


_OPTION_DEFAULTS: dict[str, object] = {
    "conditionOnPreviousText": False,
    "keepSuspectedMetadata": False,
    "retainIntermediate": False,
}

_PRESET_DEFAULTS: dict[DraftExtractionPreset, dict[str, object]] = {
    DraftExtractionPreset.FAST: {
        "asrModel": "small",
        "skipSeparation": True,
        "vadFilter": True,
        **_OPTION_DEFAULTS,
    },
    DraftExtractionPreset.RECOMMENDED: {
        "asrModel": "medium",
        "skipSeparation": True,
        "vadFilter": True,
        **_OPTION_DEFAULTS,
    },
    DraftExtractionPreset.HIGH_QUALITY: {
        "asrModel": "medium",
        "skipSeparation": False,
        "vadFilter": True,
        **_OPTION_DEFAULTS,
    },
    DraftExtractionPreset.FULL_RECOGNITION: {
        "asrModel": "medium",
        "skipSeparation": False,
        "vadFilter": False,
        **_OPTION_DEFAULTS,
    },
}

_LEGACY_DEFAULTS: dict[str, object] = {
    "asrModel": "medium",
    "skipSeparation": False,
    "vadFilter": True,
    **_OPTION_DEFAULTS,
}

_OVERRIDE_FIELDS = {
    "asrModel",
    "skipSeparation",
    "vadFilter",
    "conditionOnPreviousText",
    "keepSuspectedMetadata",
    "retainIntermediate",
}


def normalize_draft_preset(value: str | None) -> DraftExtractionPreset | None:
    """Normalize CLI/request preset spelling without losing invalid values."""

    if value is None:
        return None
    normalized = value.strip().replace("-", "_").upper()
    try:
        return DraftExtractionPreset(normalized)
    except ValueError as exc:
        raise DraftConfigError(
            "INVALID_PRESET",
            f"Unsupported draft extraction preset: {value}",
        ) from exc


def resolve_draft_extraction_config(
    *,
    preset: str | DraftExtractionPreset | None = None,
    overrides: dict[str, object | None] | None = None,
    asr_model: str | None = None,
    skip_separation: bool | None = None,
    vad_filter: bool | None = None,
    condition_on_previous_text: bool | None = None,
    keep_suspected_metadata: bool | None = None,
    retain_intermediate: bool | None = None,
) -> DraftExtractionConfig:
    """Resolve preset defaults, explicit overrides, and legacy CLI fields.

    ``None`` means "not provided". Explicit ``False`` values are preserved.
    """

    normalized_preset: DraftExtractionPreset | None
    if isinstance(preset, DraftExtractionPreset):
        normalized_preset = preset
    else:
        normalized_preset = normalize_draft_preset(preset)

    values: dict[str, object] = dict(
        _PRESET_DEFAULTS[normalized_preset] if normalized_preset is not None else _LEGACY_DEFAULTS
    )
    if overrides is not None:
        _validate_overrides(overrides)
        for key, value in overrides.items():
            if value is not None:
                values[key] = value

    explicit = {
        "asrModel": asr_model,
        "skipSeparation": skip_separation,
        "vadFilter": vad_filter,
        "conditionOnPreviousText": condition_on_previous_text,
        "keepSuspectedMetadata": keep_suspected_metadata,
        "retainIntermediate": retain_intermediate,
    }
    for key, value in explicit.items():
        if value is not None:
            values[key] = value

    return _build_config(normalized_preset, values)


def requested_draft_config_json(
    *,
    preset: str | None,
    overrides: dict[str, object | None] | None = None,
    legacy_fields: dict[str, object | None] | None = None,
) -> dict[str, object]:
    """Return only user/request supplied config fields for status.json."""

    payload: dict[str, object] = {}
    if preset is not None:
        payload["preset"] = preset
    if overrides is not None:
        payload["overrides"] = {key: value for key, value in overrides.items() if value is not None}
    if legacy_fields is not None:
        for key, value in legacy_fields.items():
            if value is not None:
                payload[key] = value
    return payload


def _validate_overrides(overrides: dict[str, object | None]) -> None:
    for key, value in overrides.items():
        if key not in _OVERRIDE_FIELDS:
            raise DraftConfigError(
                "REQUEST_INVALID",
                f"Unsupported draft extraction override: {key}",
            )
        if value is None:
            continue
        if key == "asrModel":
            if not isinstance(value, str) or not value.strip():
                raise DraftConfigError(
                    "REQUEST_INVALID",
                    "overrides.asrModel must be a non-empty string.",
                )
        elif not isinstance(value, bool):
            raise DraftConfigError("REQUEST_INVALID", f"overrides.{key} must be a boolean.")


def _build_config(
    preset: DraftExtractionPreset | None,
    values: dict[str, Any],
) -> DraftExtractionConfig:
    asr_model = values["asrModel"]
    if not isinstance(asr_model, str) or not asr_model.strip():
        raise DraftConfigError("REQUEST_INVALID", "asrModel must be a non-empty string.")
    return DraftExtractionConfig(
        preset=preset.value if preset is not None else None,
        asr_model=asr_model,
        skip_separation=_require_bool(values["skipSeparation"], "skipSeparation"),
        vad_filter=_require_bool(values["vadFilter"], "vadFilter"),
        condition_on_previous_text=_require_bool(
            values["conditionOnPreviousText"], "conditionOnPreviousText"
        ),
        keep_suspected_metadata=_require_bool(
            values["keepSuspectedMetadata"], "keepSuspectedMetadata"
        ),
        retain_intermediate=_require_bool(values["retainIntermediate"], "retainIntermediate"),
    )


def _require_bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise DraftConfigError("REQUEST_INVALID", f"{field} must be a boolean.")
    return value
