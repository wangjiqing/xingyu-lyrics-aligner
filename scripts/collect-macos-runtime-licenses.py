#!/usr/bin/env python3
from __future__ import annotations

import importlib.metadata
import json
import re
import shutil
import sys
from pathlib import Path


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def normalize_license(
    metadata: importlib.metadata.PackageMetadata, files: list[Path]
) -> str | None:
    declared = metadata.get("License-Expression") or metadata.get("License")
    if declared and declared.strip().upper() != "UNKNOWN":
        candidate = declared.strip()
        if "\n" not in candidate and len(candidate) <= 80:
            return candidate
    text = "\n".join(path.read_text(encoding="utf-8", errors="ignore")[:8000] for path in files)
    lowered = text.lower()
    if "apache license" in lowered and "version 2.0" in lowered:
        return "Apache-2.0"
    if "permission is hereby granted, free of charge" in lowered:
        return "MIT"
    if "redistribution and use in source and binary forms" in lowered:
        return "BSD-3-Clause"
    return None


def main() -> None:
    output = Path(sys.argv[1])
    repository = Path(__file__).resolve().parent.parent
    audit_path = repository / "packaging/macos/runtime/license-audit.json"
    audit_data = json.loads(audit_path.read_text(encoding="utf-8"))
    if audit_data.get("schemaVersion") != 1:
        raise RuntimeError("Unsupported license audit schema.")
    audited = {canonical(item["name"]): item for item in audit_data["packages"]}
    packages = output / "python-packages"
    packages.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, object]] = []
    installed: set[str] = set()
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata["Name"]
        key = canonical(name)
        installed.add(key)
        target = packages / key
        source_files: list[Path] = []
        copied: list[str] = []
        for item in distribution.files or []:
            filename = str(item).lower()
            if not any(marker in filename for marker in ("license", "copying", "notice")):
                continue
            source = Path(distribution.locate_file(item))
            if source.is_file():
                source_files.append(source)
                target.mkdir(parents=True, exist_ok=True)
                destination = target / source.name
                shutil.copy2(source, destination)
                copied.append(str(destination.relative_to(output)))
        entry = audited.get(key)
        if not copied:
            if entry is None or entry["version"] != distribution.version:
                raise RuntimeError(f"Missing audited license for {name}=={distribution.version}")
            source = (audit_path.parent / "licenses" / entry["licenseTextFile"]).resolve()
            if not source.is_file():
                raise RuntimeError(f"Missing curated license text: {source}")
            target.mkdir(parents=True, exist_ok=True)
            destination = target / source.name
            shutil.copy2(source, destination)
            copied.append(str(destination.relative_to(output)))
        spdx = (
            entry["spdx"]
            if entry is not None
            else normalize_license(distribution.metadata, source_files)
        )
        if not spdx or str(spdx).upper() == "UNKNOWN":
            raise RuntimeError(
                f"Missing normalized license identifier for {name}=={distribution.version}"
            )
        source_url = (
            entry["sourceUrl"]
            if entry is not None
            else (
                distribution.metadata.get("Home-page")
                or next(iter(distribution.metadata.get_all("Project-URL") or []), "")
                or f"https://pypi.org/project/{key}/{distribution.version}/"
            )
        )
        if not source_url:
            raise RuntimeError(f"Missing upstream URL for {name}=={distribution.version}")
        records.append(
            {
                "name": name,
                "version": distribution.version,
                "spdx": spdx,
                "sourceUrl": source_url,
                "licenseFiles": copied,
                "audit": entry if entry is not None else None,
            }
        )
    unexpected_audit = sorted(set(audited) - installed)
    if unexpected_audit:
        raise RuntimeError(
            f"License audit contains distributions not installed: {unexpected_audit}"
        )
    (output / "third-party-packages.json").write_text(
        json.dumps(sorted(records, key=lambda item: canonical(str(item["name"]))), indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
