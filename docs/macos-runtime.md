# macOS bundled runtime

The runtime manifest records Xcode, clang, macOS SDK, and host macOS versions and inventories every distributed regular file or controlled relative symlink. Bundle verification compares the inventory in both directions and identifies Mach-O files by magic bytes rather than filename extensions. The FFmpeg cache has its own manifest binding source, configure arguments, toolchain, architecture, and output hashes.

Two clean outputs should have identical inventories on the same controlled host. This is an engineering consistency check, not a cross-machine byte-for-byte reproducibility claim.

The final 0.7.0 candidate Runtime contains 31,455 inventory entries and is about
1.0 GiB on disk. Two clean outputs on the release host had identical path sets,
file hashes, and runtime manifests. The signed App payload is measured
separately because ad-hoc signatures necessarily change Mach-O bytes.

The v0.7.0 candidate builds an Apple Silicon Release App with a relocatable
Python 3.11 Runtime, an unsigned DMG, and inside-out ad-hoc signing. It is not a
Developer ID signed or notarized release.

## Pinned inputs

- python-build-standalone CPython 3.11.15, release 20260510, arm64 stripped
- FFmpeg 7.1.3 official source, locally compiled arm64/LGPL
- Exact Python versions in `packaging/macos/runtime/requirements.lock`
- Exact macOS arm64 wheel hashes in `requirements-hashes.lock` and
  `wheelhouse-manifest.json`
- Checksums and URLs in `runtime-source.json` and `checksums.txt`

FFmpeg 8.1 was tested first but rejected because TorchCodec 0.7.0 only supports
FFmpeg ABIs 4–7. FFmpeg 7.1.3 provides the compatible `libav*` shared libraries,
`ffmpeg`, and `ffprobe` without GPL/nonfree configuration.

## Build and verify

```bash
scripts/build-macos-runtime.sh
scripts/build-macos-app.sh
scripts/verify-macos-bundle.sh
scripts/smoke-macos-app.sh
XINGYU_SMOKE_TRACKS=1 scripts/smoke-macos-app.sh
scripts/package-macos-dmg.sh --overwrite
```

Outputs are `build/macos-runtime/runtime` and
`dist/macos/星语歌词对齐器.app`. Cached, checksum-verified sources and dependency
layers are under `.build-cache/macos-runtime`. Remove those three directories to
force a completely clean rebuild.

The Bundle runtime contains `bin/python3`, `bin/ffmpeg`, `bin/ffprobe`, the
standard library/site-packages, FFmpeg dylibs, NLTK punkt data, licenses,
`packages.freeze.txt`, and `runtime-manifest.json`. Runtime installation uses
`--no-index`, `--find-links`, and `--require-hashes`. Universal wheels are
thinned to arm64. The PyTorch wheel's bundled `libomp` install ID is made
relocatable. `sign-macos-app.sh` signs dylibs, Python extensions, nested
executables, the main executable, and the outer App in that inside-out order.
Ad-hoc signing is not Developer ID signing.

Models remain in `~/Library/Application Support/XingyuLyricsAligner/Models` and
survive replacing or deleting the app. Release uses the Bundle runtime first
and never searches a repository `.venv` or system Python. Debug retains explicit
development overrides.

The candidate is ad-hoc signed, unnotarized, and not sandboxed. The DMG filename
contains `unsigned` because it has no Apple-trusted Developer ID signature.

## Measured v0.7.0 candidate size

The final verified arm64 build measured 1,063,668 KiB for the Runtime and
1,077,052 KiB for the complete App. `site-packages` used 961,076 KiB; PyTorch
345,560 KiB; WhisperX 17,472 KiB; Transformers 55,672 KiB; ONNX Runtime 69,188
KiB; CTranslate2 4,848 KiB; Demucs code 400 KiB; FFmpeg shared libraries
20,116 KiB; and NLTK data 10,856 KiB. Values come from `du -sk` after final
ad-hoc signing and exclude separately managed model weights.
