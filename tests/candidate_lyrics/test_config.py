from __future__ import annotations

import pytest

from xingyu_lyrics_aligner.candidate_lyrics.config import (
    DraftConfigError,
    resolve_draft_extraction_config,
)


def test_draft_presets_resolve_expected_defaults() -> None:
    assert resolve_draft_extraction_config(preset="fast").to_worker_json() | {"device": "cpu"} == {
        "preset": "FAST",
        "asrModel": "small",
        "skipSeparation": True,
        "vadFilter": True,
        "conditionOnPreviousText": False,
        "keepSuspectedMetadata": False,
        "retainIntermediate": False,
        "device": "cpu",
    }
    assert resolve_draft_extraction_config(preset="recommended").skip_separation is True
    assert resolve_draft_extraction_config(preset="high-quality").skip_separation is False
    assert resolve_draft_extraction_config(preset="full-recognition").vad_filter is False


def test_legacy_default_preserves_existing_behavior() -> None:
    config = resolve_draft_extraction_config()

    assert config.preset is None
    assert config.asr_model == "medium"
    assert config.skip_separation is False
    assert config.vad_filter is True


def test_explicit_overrides_win_over_preset_and_false_is_preserved() -> None:
    config = resolve_draft_extraction_config(
        preset="recommended",
        overrides={"asrModel": "large-v3", "skipSeparation": False, "vadFilter": False},
    )

    assert config.asr_model == "large-v3"
    assert config.skip_separation is False
    assert config.vad_filter is False


def test_invalid_preset_and_override_raise_stable_codes() -> None:
    with pytest.raises(DraftConfigError) as preset_error:
        resolve_draft_extraction_config(preset="maximum")
    assert preset_error.value.code == "INVALID_PRESET"

    with pytest.raises(DraftConfigError) as override_error:
        resolve_draft_extraction_config(
            preset="fast",
            overrides={"vadFilter": "false"},
        )
    assert override_error.value.code == "REQUEST_INVALID"
