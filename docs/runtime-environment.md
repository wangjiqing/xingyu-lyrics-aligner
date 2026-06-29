# Runtime Environment

This page documents v0.1.1 runtime paths, model choices, and configuration
boundaries. It is meant for installation review and troubleshooting.

## CLI Entry Points

Recommended user command:

```bash
xingyu-align
```

Compatibility alias:

```bash
xingyu-lyrics-aligner
```

Both entry points call the same Typer application:

```text
xingyu_lyrics_aligner.cli:app
```

Development fallback:

```bash
python -m xingyu_lyrics_aligner.cli
```

## User Preferences

The CLI can persist user preferences in:

```text
~/.config/xingyu-lyrics-aligner/config.json
```

Currently persisted:

```json
{
  "locale": "zh-CN"
}
```

Locale priority:

```text
--locale option
> XINGYU_ALIGN_LOCALE environment variable
> saved user config
> en-US default
```

Set or inspect the saved preference:

```bash
xingyu-align config set-locale zh-CN
xingyu-align config show
```

The macOS installer also accepts:

```bash
./scripts/install-macos.sh --locale zh-CN
```

When run interactively without `--locale`, the installer asks for a default CLI
language and saves the choice.

## Alignment Model

v0.1.1 supports Chinese trusted-lyrics CTC alignment with:

```text
jonatasgrosman/wav2vec2-large-xlsr-53-chinese-zh-cn
```

Source:

```text
https://huggingface.co/jonatasgrosman/wav2vec2-large-xlsr-53-chinese-zh-cn
```

The model is loaded through WhisperX `load_align_model`. `models pull` only
downloads/preheats the alignment model. It does not run ASR transcription and
does not create song outputs.

Download size is determined by upstream Hugging Face model files and may change
outside this project.

## Model Cache

The project does not bundle model weights. Hugging Face and Transformers decide
the default cache location, normally under the user's home cache, such as:

```text
~/.cache/huggingface/
```

Common environment variables from the Hugging Face ecosystem can override this,
for example:

```bash
export HF_HOME="/path/to/hf-cache"
export HUGGINGFACE_HUB_CACHE="/path/to/hf-cache/hub"
```

Xingyu Lyrics Aligner does not delete model caches.

## Project Installation Directory

The macOS installer supports source-checkout and GitHub install modes.

Source-checkout mode creates or reuses:

```text
<repo>/.venv/
```

The editable install points to the current checkout. Moving or deleting the
checkout can break the launcher until the installer is rerun.

GitHub install mode creates or reuses:

```text
~/.local/share/xingyu-lyrics-aligner/venv/
```

It installs from a Git ref such as `main` or `v0.3.0`.

## User Launcher

The macOS installer creates:

```text
~/.local/bin/xingyu-align
```

The launcher is a small wrapper that executes:

```text
<repo>/.venv/bin/xingyu-align
```

In GitHub install mode, the launcher points to:

```text
~/.local/share/xingyu-lyrics-aligner/venv/bin/xingyu-align
```

The installer does not modify shell config. If `~/.local/bin` is not on `PATH`,
add it manually.

## Output Directory

The user chooses the output directory:

```bash
xingyu-align align --output-dir "/path/to/output"
```

v0.3.0 writes:

```text
alignment.json
lyrics.lrc
lyrics.swlrc
report.json
```

With `--debug-output`, it may also write:

```text
debug.summary.json
```

Use `--overwrite` to replace existing output files.

## Configuration Boundary

v0.1.1 has a small user preference file for behavior such as default locale.
Alignment job choices are still passed as CLI options:

- `--language`
- `--device`
- `--section-manifest`
- `--lrc-offset-ms`
- `--overwrite`
- `--debug-output`

The existing `config.py` module is reserved and not wired into v0.1.1 runtime
commands.

## Device Behavior

Supported user-facing values:

```text
auto
cpu
cuda
mps
```

For WhisperX CTC alignment, `mps` may fall back to CPU. Outputs record both the
requested and actual alignment devices.

## Files Not Managed By The Installer

The installer and uninstaller do not delete:

- `.venv/`
- Hugging Face model caches;
- alignment outputs;
- user music files;
- trusted lyric files.

Only `scripts/uninstall-macos.sh` removes the user launcher:

```text
~/.local/bin/xingyu-align
```
