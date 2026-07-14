"""Device strategy and runtime capability detection."""

from __future__ import annotations

import importlib.util
import os
import platform
from enum import StrEnum
from importlib import import_module
from shutil import which
from typing import Any

from pydantic import BaseModel, Field


class DeviceStrategy(StrEnum):
    """User-facing device selection strategy."""

    AUTO = "auto"
    CPU = "cpu"
    CUDA = "cuda"
    MPS = "mps"


class DeviceCapabilities(BaseModel):
    """Detected local hardware/runtime capabilities."""

    python_version: str
    os_name: str
    os_release: str
    machine: str
    is_apple_silicon: bool
    cuda_available: bool = Field(
        description="True only when torch is installed and reports CUDA availability."
    )
    mps_available: bool = Field(
        description="True only when torch is installed and reports Apple MPS availability."
    )
    ffmpeg_path: str | None


def detect_torch_accelerators() -> tuple[bool, bool]:
    """Detect CUDA and MPS through torch only if torch is already installed."""
    if importlib.util.find_spec("torch") is None:
        return False, False

    torch: Any = import_module("torch")

    cuda_available = bool(torch.cuda.is_available())
    mps_backend = getattr(torch.backends, "mps", None)
    mps_available = bool(mps_backend and mps_backend.is_available())
    return cuda_available, mps_available


def detect_device_capabilities() -> DeviceCapabilities:
    """Return a structured snapshot suitable for future JSON doctor output."""
    cuda_available, mps_available = detect_torch_accelerators()
    machine = platform.machine()
    return DeviceCapabilities(
        python_version=platform.python_version(),
        os_name=platform.system(),
        os_release=platform.release(),
        machine=machine,
        is_apple_silicon=platform.system() == "Darwin" and machine in {"arm64", "aarch64"},
        cuda_available=cuda_available,
        mps_available=mps_available,
        ffmpeg_path=explicit_or_path_executable("XINGYU_ALIGNER_FFMPEG", "ffmpeg"),
    )


def explicit_or_path_executable(environment_name: str, command: str) -> str | None:
    """Resolve a controlled executable override before consulting PATH."""
    configured = os.environ.get(environment_name)
    if configured:
        return configured if os.path.isfile(configured) and os.access(configured, os.X_OK) else None
    return which(command)
