"""Alignment model lifecycle helpers."""

from __future__ import annotations

import importlib.util
import socket
from dataclasses import dataclass

from xingyu_lyrics_aligner.alignment.ctc import DEFAULT_ALIGN_MODEL, resolve_alignment_device
from xingyu_lyrics_aligner.device import DeviceStrategy

SUPPORTED_ALIGNMENT_MODELS = {
    "zh": DEFAULT_ALIGN_MODEL,
    "zh-cn": DEFAULT_ALIGN_MODEL,
    "zh-CN": DEFAULT_ALIGN_MODEL,
}


@dataclass(frozen=True)
class AlignmentModelStatus:
    """Local availability of an alignment model."""

    language: str
    model_name: str
    available: bool
    detail: str


@dataclass(frozen=True)
class AlignmentModelPullResult:
    """Result of an explicit model pull/preheat."""

    language: str
    model_name: str
    actual_device: str
    warnings: list[str]


def resolve_alignment_model(language: str) -> str:
    """Resolve a language hint to the v0.1.1 alignment model."""
    key = language.strip()
    normalized = key.lower()
    if key in SUPPORTED_ALIGNMENT_MODELS:
        return SUPPORTED_ALIGNMENT_MODELS[key]
    if normalized in SUPPORTED_ALIGNMENT_MODELS:
        return SUPPORTED_ALIGNMENT_MODELS[normalized]
    raise ValueError("Only Chinese alignment is supported in v0.1.1. Use --language zh.")


def alignment_model_status(language: str) -> AlignmentModelStatus:
    """Check whether the Chinese alignment model appears in local HF cache."""
    model_name = resolve_alignment_model(language)
    if importlib.util.find_spec("huggingface_hub") is None:
        return AlignmentModelStatus(
            language=language,
            model_name=model_name,
            available=False,
            detail="huggingface_hub is not installed; install the alignment extra first.",
        )
    from huggingface_hub import try_to_load_from_cache

    required_configs = [
        try_to_load_from_cache(model_name, "config.json"),
        try_to_load_from_cache(model_name, "preprocessor_config.json"),
    ]
    weights = [
        try_to_load_from_cache(model_name, "pytorch_model.bin"),
        try_to_load_from_cache(model_name, "model.safetensors"),
    ]
    available = all(isinstance(path, str) for path in required_configs) and any(
        isinstance(weight, str) for weight in weights
    )
    detail = "available in local cache" if available else "not found in local cache"
    return AlignmentModelStatus(
        language=language,
        model_name=model_name,
        available=available,
        detail=detail,
    )


def pull_alignment_model(
    *,
    language: str,
    device: DeviceStrategy,
) -> AlignmentModelPullResult:
    """Explicitly download/preheat the WhisperX CTC alignment model."""
    model_name = resolve_alignment_model(language)
    status = alignment_model_status(language)
    if not status.available:
        ensure_huggingface_reachable()
    if importlib.util.find_spec("whisperx") is None:
        raise RuntimeError(
            "WhisperX is not installed. Install with `python -m pip install -e .[alignment]` "
            "or run scripts/install-macos.sh from the source checkout."
        )
    import whisperx

    resolved_device = resolve_alignment_device(device)
    try:
        whisperx.load_align_model(
            language_code=language,
            device=resolved_device.actual,
            model_name=model_name,
            model_cache_only=status.available,
        )
    except PermissionError as exc:
        raise RuntimeError(
            "Model cache is not writable. Check Hugging Face cache permissions."
        ) from exc
    except OSError as exc:
        raise RuntimeError(
            "Failed to download or load the alignment model. Check network access and cache path."
        ) from exc
    except Exception as exc:
        raise RuntimeError(f"Failed to prepare alignment model: {exc}") from exc

    return AlignmentModelPullResult(
        language=language,
        model_name=model_name,
        actual_device=resolved_device.actual,
        warnings=resolved_device.warnings,
    )


def ensure_huggingface_reachable() -> None:
    """Fail quickly when DNS/network is unavailable before HF retry loops."""
    try:
        with socket.create_connection(("huggingface.co", 443), timeout=5.0):
            return
    except OSError as exc:
        raise RuntimeError(
            "Cannot reach huggingface.co. Check network/DNS, proxy, or VPN, then rerun "
            "`xingyu-align models pull --language zh`."
        ) from exc
