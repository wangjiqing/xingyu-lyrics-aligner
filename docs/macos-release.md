# macOS v0.7.0 release candidate

This document describes the Apple Silicon unsigned candidate workflow. It does
not create a Git tag, GitHub Release, Developer ID signature, or notarization.

## Build

Refresh dependency inputs only when deliberately changing source/dependencies:

```bash
scripts/prepare-macos-wheelhouse.sh --refresh-lock
```

Normal candidate builds verify the tracked lock and cached wheelhouse without
resolving packages from the network during Runtime installation:

```bash
scripts/build-macos-release-candidate.sh --overwrite
```

The sequence verifies the wheelhouse, builds Runtime and Release App, applies
inside-out ad-hoc signatures, verifies/smokes the standalone App, runs the
dual-track smoke, packages and verifies the DMG, and produces:

```text
dist/macos/星语歌词对齐器.app
dist/macos/星语歌词对齐器-0.7.0-arm64-unsigned.dmg
dist/macos/星语歌词对齐器-0.7.0-arm64-unsigned.dmg.sha256
dist/macos/星语歌词对齐器.app.sha256
dist/macos/release-manifest.json
dist/macos/release-manifest.json.sha256
```

The release manifest records App, Engine, and Python package `0.7.0` separately
from Runtime `v1`. It explicitly records `developerIdSigned=false`,
`signatureType=ADHOC`, `notarized=false`, `gatekeeperTrusted=false`, and
`modelsBundled=false`; ad-hoc signing is not an Apple-trusted distribution
signature.

The current final candidate is approximately 979 MiB as an App payload and
273 MiB as a compressed DMG; the exact byte counts are generated into
`release-manifest.json` from the candidate artifacts. The App checksum is a
canonical sorted tree digest (including file contents and symlink targets),
because an `.app` is a directory rather than a single byte stream.

## Acceptance

Run Python regression, Xcode Release build/tests, `verify-macos-bundle.sh`,
`smoke-macos-app.sh`, `hdiutil verify/attach/detach`, `codesign --verify`, and
`spctl --assess`. Gatekeeper rejection for an ad-hoc build is expected and must
be reported, not converted into a false success. Quarantine testing must record
the actual host macOS behavior.

The build cache and `dist/` are ignored. The wheelhouse itself stays in
`.build-cache/macos-runtime/wheelhouse`; Git tracks its manifest and hashes, not
the large wheel files. Updating it requires explicit `--refresh-lock` and review
of filename, version, source, SHA-256, platform tags, and license changes.
