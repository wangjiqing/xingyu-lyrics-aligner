# macOS arm64 runtime inputs

`runtime-source.json`, `checksums.txt`, `requirements.lock`,
`requirements-hashes.lock`, and `wheelhouse-manifest.json` are the pinned
inputs. Python is an arm64 relocatable python-build-standalone distribution.
FFmpeg and FFprobe are built locally from the pinned official source with GPL
and nonfree components disabled. Model weights are never copied into this
runtime.

Run `scripts/build-macos-runtime.sh`. Cached source archives live under
`.build-cache/macos-runtime/downloads`; delete `.build-cache/macos-runtime` and
`build/macos-runtime` for a completely clean rebuild.

Refresh the wheel lock only as an explicit dependency/source update:

```bash
scripts/prepare-macos-wheelhouse.sh --refresh-lock
```

Large wheels remain in `.build-cache/macos-runtime/wheelhouse` rather than Git.
Normal builds verify every file and install with `--no-index --find-links
--require-hashes`. `antlr4-python3-runtime 4.9.3` and `jieba 0.42.1` have no
upstream wheel; their pinned sdist inputs and deterministic build metadata are
recorded in `runtime-source.json` and the manifest. The current project wheel is
also hashed, so Python source or README metadata changes require an explicit
refresh.
