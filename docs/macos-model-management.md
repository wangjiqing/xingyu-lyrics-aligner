# macOS Desktop Model Management

## Integrity and recoverable installation

Critical manifest files carry pinned SHA-256 values; the alignment weight also records its Hugging Face LFS OID. Readiness rejects symlinks, non-regular files, paths escaping the model root, and digest mismatches. Its integrity cache is bound to size, nanosecond mtime, manifest revision, and the expected digest.

Each installation uses `Models/.transactions/<model-id>.json` plus a per-model lock. Staging, backup, activation, rollback, cancellation, and completion are journaled. Readiness recovers transactions whose owner process no longer exists. Downloads require HTTPS and HTTPS-to-HTTP redirects are rejected.

The v0.7.0 native App provides explicit, user-initiated model preparation with
its bundled Python/FFmpeg Runtime. Weights still live in Application Support and
are never written into the read-only App Bundle or distributed in the DMG.

## Readiness check

The app runs the selected development Python directly, without a shell:

```bash
python -m xingyu_lyrics_aligner.cli desktop readiness --json
```

The versioned JSON reports Python, FFmpeg, FFprobe, managed models, expected and
installed revisions, installation problems, `readyForAlignment`, and
`readyForSeparation`. Model states are `NOT_INSTALLED`, `DOWNLOADING`,
`INSTALLED`, `INCOMPLETE`, `REVISION_MISMATCH`, `CORRUPTED`, and `UNKNOWN`.
A directory alone is never accepted: `install-state.json`, its revision, every
required file, and each minimum size must pass validation.

Development builds may report FFmpeg and FFprobe from the development PATH.
The Release App reports and uses only its bundled FFmpeg/FFprobe paths. The app
never runs Homebrew or changes the user's shell configuration.

## Managed models

### Required Chinese alignment model

- Desktop ID: `alignment.zh.whisperx`
- Source: `jonatasgrosman/wav2vec2-large-xlsr-53-chinese-zh-cn`
- Pinned revision: `99ccb2737be22b8bb50dcfcc39ad4d567fb90cfd`
- Expected download: 1,276,342,318 bytes (about 1.19 GiB)
- Declared license: Apache-2.0 in the pinned Hugging Face model metadata/card
- Files: `config.json`, `preprocessor_config.json`, `pytorch_model.bin`,
  `special_tokens_map.json`, and `vocab.json`

This is required for trusted-lyrics alignment. Lyrics tasks remain disabled
until it and the WhisperX Python package are ready.

### Optional separation model

- Desktop ID: `separation.demucs.htdemucs`
- Model/checkpoint: `htdemucs`, `955717e8-8726e21a.th`
- Pinned Demucs catalog revision: `e976d93ecc3865e5757426930257e200846a520a`
- Expected checkpoint download: 84,141,911 bytes (about 80.24 MiB)
- Project/catalog license: MIT at the pinned Demucs revision
- Files: `955717e8-8726e21a.th` and managed `htdemucs.yaml`

This weight is optional. Its absence does not block LRC/SWLRC-only jobs. A
vocals or accompaniment export requires both the checkpoint and optional
`demucs` Python package. `demucs_package_missing` is reported separately from a
missing weight; reinstalling the weight does not install the package.

Installation is a user-initiated download from pinned upstream locations. The
v0.7.0 DMG does not redistribute either weight; their independent license and
pinned source notices are included with the App.

## Installation and real progress

```bash
python -m xingyu_lyrics_aligner.cli models install <desktop-model-id> --json-events
```

The command emits JSON lines: `INSTALL_STARTED`, `DOWNLOAD_PROGRESS`,
`VERIFYING`, `INSTALLING`, `INSTALL_SUCCEEDED`, `INSTALL_FAILED`, and
`INSTALL_CANCELLED`. Progress is actual bytes written; `totalBytes` may be null.
No percentage or ETA is invented.

Downloads enter `Downloads/<model-id>.partial`. A completed download is
validated, receives `install-state.json`, and is atomically moved into the model
directory. Failed/cancelled staging data is removed. A failed replacement keeps
the previously installed model.

## Application Support layout

```text
~/Library/Application Support/XingyuLyricsAligner/
├── Development/Jobs/
├── Development/Music/
├── Models/Alignment/
├── Models/Separation/
├── ModelManifests/
├── Downloads/
├── Runtime/
├── Cache/
└── Logs/
```

`XINGYU_APP_SUPPORT_DIR` can select a fresh test root. Install and Worker
processes receive explicit values for `HF_HOME`, `HUGGINGFACE_HUB_CACHE`,
`TRANSFORMERS_CACHE`, `TORCH_HOME`, `XDG_CACHE_HOME`, `NLTK_DATA`,
`XINGYU_ALIGNMENT_MODEL_DIR`, and `XINGYU_DEMUCS_MODEL_REPO`.

WhisperX receives the formal alignment directory and remains cache-only. Demucs
receives the formal managed repository with `--repo`; neither route relies on
the user's default `~/.cache/huggingface` or `~/.cache/torch`.

## Remove, reinstall, and offline use

Exit the app and Worker first. Delete the relevant directory under
`Models/Alignment` or `Models/Separation`, then run readiness again. The next
install is a fresh download; v0.7.0 does not resume partial downloads.
`Downloads/*.partial` may be deleted while no installer is running.

An installed alignment model supports offline work when the development Python
dependencies and FFmpeg remain installed. Installation requires network access.
v0.7.0 does not install ASR models.
