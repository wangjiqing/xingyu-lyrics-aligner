"""Doctor checks for the bootstrap CLI."""

from __future__ import annotations

from pydantic import BaseModel

from xingyu_lyrics_aligner.device import DeviceCapabilities, detect_device_capabilities


class DoctorReport(BaseModel):
    """Structured doctor report reserved for future JSON output."""

    capabilities: DeviceCapabilities
    warnings: list[str]


def run_doctor() -> DoctorReport:
    """Run lightweight local checks without downloading models."""
    capabilities = detect_device_capabilities()
    warnings: list[str] = []
    if capabilities.ffmpeg_path is None:
        warnings.append("ffmpeg_missing")
    return DoctorReport(capabilities=capabilities, warnings=warnings)
