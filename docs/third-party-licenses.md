# Third-party runtime licenses

The Phase D2 macOS runtime is assembled from pinned upstream artifacts and
Python wheels. The generated bundle contains `runtime/licenses/Python-LICENSE.txt`,
`FFmpeg-LGPL-2.1.txt`, copied wheel license/notice files, and a versioned
`third-party-packages.json` inventory.

Phase E1 replaces the upstream PyAV binary wheel with PyAV 14.4.0 built from
its pinned sdist against this same LGPL-only FFmpeg 7.1.3. The Runtime verifier
rejects `libx264`, `libx265`, and `libSvtAv1Enc`; PyAV 17.1.0 was not used
because its generated sources do not compile against FFmpeg 7.1.3. The strict
`third-party-packages.json` inventory must match every installed distribution,
and every entry must have a normalized license identifier, upstream URL, and
at least one bundled license/notice file. Version-pinned manual audit entries
cover wheels whose RECORD omits those files.

The python-build-standalone base archive components are separately recorded in
`base-runtime-components.json`, including CPython, OpenSSL, SQLite, Tcl/Tk,
libffi, xz/liblzma, and zlib.

Key components include CPython/PSF License, python-build-standalone's bundled
component notices, PyTorch/BSD-3-Clause, WhisperX/BSD-2-Clause, Transformers and
Hugging Face Hub/Apache-2.0, Demucs/MIT, CTranslate2/MIT, ONNX Runtime/MIT,
Typer/MIT, Pydantic/MIT, NLTK/Apache-2.0, and FFmpeg/LGPL-2.1-or-later.

FFmpeg 7.1.3 is built by this project from the official source archive
<https://ffmpeg.org/releases/ffmpeg-7.1.3.tar.xz>, SHA-256
`f0bf043299db9e3caacb435a712fc541fbb07df613c4b893e8b77e67baf3adbe`.
It uses `--disable-gpl --disable-nonfree --disable-doc --disable-debug
--disable-autodetect --enable-ffmpeg --enable-ffprobe --enable-shared
--disable-static`. The source is not modified; post-build install names/rpaths
are made Bundle-relative. The resulting dylibs are dynamically linked and
distributed under LGPL-2.1-or-later. No Homebrew executable is redistributed,
and the binary is not represented as an official FFmpeg prebuilt. Recipients
can obtain the corresponding unmodified source from that URL and verify the
recorded checksum.

The App and DMG `Licenses/` materials include `THIRD-PARTY-NOTICES.md`,
`FFmpeg-LICENSE.txt`, `Python-LICENSE.txt`, `third-party-packages.json`, copied
wheel license/notice files, the project Apache-2.0 license, and
`model-licenses.md`.

Alignment and Demucs model weights remain outside the App Bundle. Their model
card/catalog license information is covered by `macos-model-management.md` and
must be reviewed independently before redistribution. Phase D2 performs
user-initiated model downloads and does not grant a new redistribution right.
