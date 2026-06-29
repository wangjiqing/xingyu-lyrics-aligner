"""Typer CLI entrypoint."""

from __future__ import annotations

import subprocess
import sys
from argparse import Namespace
from pathlib import Path
from typing import Annotated, cast

import typer

from xingyu_lyrics_aligner import __version__
from xingyu_lyrics_aligner.alignment.models import alignment_model_status, pull_alignment_model
from xingyu_lyrics_aligner.candidate_lyrics.script_normalization import (
    ScriptNormalizationError,
    normalize_transcript_script,
)
from xingyu_lyrics_aligner.candidate_lyrics.transcription import (
    CandidateLyricsError,
    extract_candidate_lyrics,
)
from xingyu_lyrics_aligner.commands.align import align_command
from xingyu_lyrics_aligner.device import DeviceStrategy
from xingyu_lyrics_aligner.doctor import run_doctor
from xingyu_lyrics_aligner.i18n import configure_locale, normalize_locale
from xingyu_lyrics_aligner.i18n import translate as _
from xingyu_lyrics_aligner.model_registry import known_model_slots
from xingyu_lyrics_aligner.user_config import UserConfig, load_user_config, save_user_config
from xingyu_lyrics_aligner.worker import run_worker

HELP_CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}

app = typer.Typer(
    help=_("app.help"),
    epilog=_("app.epilog"),
    no_args_is_help=True,
    invoke_without_command=True,
    context_settings=HELP_CONTEXT_SETTINGS,
)
models_app = typer.Typer(
    help=_("command.models.help"),
    invoke_without_command=True,
    no_args_is_help=False,
    context_settings=HELP_CONTEXT_SETTINGS,
)
config_app = typer.Typer(
    help=_("command.config.help"),
    no_args_is_help=True,
    context_settings=HELP_CONTEXT_SETTINGS,
)
candidate_app = typer.Typer(
    help=_("command.candidate.help"),
    epilog=_("candidate.epilog"),
    no_args_is_help=True,
    context_settings=HELP_CONTEXT_SETTINGS,
)
worker_app = typer.Typer(
    help=_("command.worker.help"),
    no_args_is_help=True,
    context_settings=HELP_CONTEXT_SETTINGS,
)
app.add_typer(models_app, name="models")
app.add_typer(config_app, name="config")
app.add_typer(candidate_app, name="candidate")
app.add_typer(worker_app, name="worker")

MODEL_DISPLAY_KEYS = {
    "forced-aligner": "models.slot.aligner",
    "vocal-separator": "models.slot.separator",
}
GITHUB_REPOSITORY_URL = "https://github.com/wangjiqing/xingyu-lyrics-aligner.git"


def _localized_bool(value: bool) -> str:
    return _("label.yes") if value else _("label.no")


def _model_display_name(model_id: str, fallback: str) -> str:
    key = MODEL_DISPLAY_KEYS.get(model_id)
    return _(key) if key else fallback


@app.callback(context_settings=HELP_CONTEXT_SETTINGS)
def main(
    locale: Annotated[
        str | None,
        typer.Option("--locale", help=_("option.locale.help")),
    ] = None,
    version_requested: Annotated[
        bool,
        typer.Option("--version", help=_("command.version.help"), is_eager=True),
    ] = False,
) -> None:
    """Configure process-wide CLI locale."""
    configure_locale(locale)
    if version_requested:
        typer.echo(f"xingyu-lyrics-aligner {__version__}")
        raise typer.Exit()


@app.command("version", help=_("command.version.help"), context_settings=HELP_CONTEXT_SETTINGS)
def version() -> None:
    """Show package version."""

    typer.echo(f"xingyu-lyrics-aligner {__version__}")


def _upgrade_command(include_candidate_lyrics: bool, ref: str) -> list[str]:
    extra = "[candidate-lyrics]" if include_candidate_lyrics else ""
    package = f"xingyu-lyrics-aligner{extra} @ git+{GITHUB_REPOSITORY_URL}@{ref}"
    return [sys.executable, "-m", "pip", "install", "--upgrade", package]


@app.command("help", help=_("command.help.help"), context_settings=HELP_CONTEXT_SETTINGS)
@app.command("manual", help=_("command.help.help"), context_settings=HELP_CONTEXT_SETTINGS)
def help_command() -> None:
    """Show workflow-oriented help."""

    typer.echo(_("help.workflow"))


@app.command("update", help=_("command.update.help"), context_settings=HELP_CONTEXT_SETTINGS)
@app.command("upgrade", help=_("command.update.help"), context_settings=HELP_CONTEXT_SETTINGS)
def update(
    run: Annotated[
        bool,
        typer.Option("--run", help=_("option.update_run.help")),
    ] = False,
    candidate_lyrics: Annotated[
        bool,
        typer.Option("--candidate-lyrics", help=_("option.update_candidate_lyrics.help")),
    ] = False,
    ref: Annotated[
        str,
        typer.Option("--ref", help=_("option.update_ref.help")),
    ] = "main",
) -> None:
    """Print or run the recommended package upgrade command."""

    command = _upgrade_command(candidate_lyrics, ref)
    typer.echo(_("update.current_version", version=__version__))
    typer.echo(_("update.ref", ref=ref))
    typer.echo(_("update.command", command=" ".join(command)))
    if not run:
        typer.echo(_("update.dry_run_notice"))
        return
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as exc:
        typer.echo(_("update.failed", code=exc.returncode), err=True)
        raise typer.Exit(code=exc.returncode) from exc
    typer.echo(_("update.completed"))


@app.command(help=_("command.doctor.help"), context_settings=HELP_CONTEXT_SETTINGS)
def doctor() -> None:
    """Check local runtime prerequisites."""
    report = run_doctor()
    caps = report.capabilities
    typer.echo(_("doctor.title"))
    typer.echo(f"{_('doctor.python')}: {caps.python_version}")
    typer.echo(f"{_('doctor.os')}: {caps.os_name} {caps.os_release}")
    typer.echo(f"{_('doctor.machine')}: {caps.machine}")
    typer.echo(f"{_('doctor.apple_silicon')}: {_localized_bool(caps.is_apple_silicon)}")
    typer.echo(
        f"{_('doctor.cuda')}: "
        f"{_('doctor.available') if caps.cuda_available else _('doctor.not_available')}"
    )
    typer.echo(
        f"{_('doctor.mps')}: "
        f"{_('doctor.available') if caps.mps_available else _('doctor.not_available')}"
    )
    ffmpeg_status = caps.ffmpeg_path if caps.ffmpeg_path else _("doctor.not_detected")
    typer.echo(f"{_('doctor.ffmpeg')}: {ffmpeg_status}")
    typer.echo(_("doctor.summary.ready"))


@config_app.command(
    "show",
    help=_("command.config.show.help"),
    context_settings=HELP_CONTEXT_SETTINGS,
)
def config_show() -> None:
    """Show saved user preferences."""
    config = load_user_config()
    typer.echo(_("config.title"))
    typer.echo(f"{_('label.language')}: {config.locale or _('config.locale.not_set')}")


@config_app.command(
    "set-locale",
    help=_("command.config.set_locale.help"),
    context_settings=HELP_CONTEXT_SETTINGS,
)
def config_set_locale(
    locale: Annotated[
        str,
        typer.Argument(help=_("option.locale.help")),
    ],
) -> None:
    """Persist the default CLI locale."""
    normalized = normalize_locale(locale)
    if normalized != locale:
        typer.echo(_("error.unsupported_locale", locale=locale), err=True)
        raise typer.Exit(code=2)
    try:
        path = save_user_config(UserConfig(locale=normalized))
    except OSError as exc:
        typer.echo(_("error.config_write_failed", error=exc), err=True)
        raise typer.Exit(code=2) from exc
    configure_locale(normalized)
    typer.echo(_("config.locale.saved", locale=normalized, path=path))


@candidate_app.command(
    "extract",
    help=_("command.candidate.extract.help"),
    epilog=_("candidate.extract.epilog"),
    context_settings=HELP_CONTEXT_SETTINGS,
)
def candidate_extract(
    audio: Annotated[
        Path,
        typer.Option("--audio", help=_("option.audio.help")),
    ],
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help=_("option.candidate_output_dir.help")),
    ],
    language: Annotated[
        str | None,
        typer.Option("--language", help=_("option.language.help")),
    ] = None,
    model: Annotated[
        str,
        typer.Option("--model", help=_("option.candidate_model.help")),
    ] = "medium",
    device: Annotated[
        DeviceStrategy,
        typer.Option("--device", help=_("option.device.help")),
    ] = DeviceStrategy.AUTO,
    skip_separation: Annotated[
        bool,
        typer.Option("--skip-separation", help=_("option.candidate_skip_separation.help")),
    ] = False,
    no_vad: Annotated[
        bool,
        typer.Option("--no-vad", help=_("option.candidate_no_vad.help")),
    ] = False,
    condition_on_previous_text: Annotated[
        bool,
        typer.Option(
            "--condition-on-previous-text",
            help=_("option.candidate_condition_on_previous_text.help"),
        ),
    ] = False,
    keep_suspected_metadata: Annotated[
        bool,
        typer.Option(
            "--keep-suspected-metadata",
            help=_("option.candidate_keep_suspected_metadata.help"),
        ),
    ] = False,
    keep_intermediates: Annotated[
        bool,
        typer.Option("--keep-intermediates", help=_("option.candidate_keep_intermediates.help")),
    ] = False,
) -> None:
    """Extract ASR candidate lyrics from local audio."""

    args = Namespace(
        audio=audio,
        output_dir=output_dir,
        language=language,
        model=model,
        device=device.value,
        skip_separation=skip_separation,
        no_vad=no_vad,
        condition_on_previous_text=condition_on_previous_text,
        keep_suspected_metadata=keep_suspected_metadata,
        keep_intermediates=keep_intermediates,
    )
    try:
        report = extract_candidate_lyrics(args)
    except CandidateLyricsError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(_("candidate.extract.completed", path=_candidate_cleaned_output(report)))
    typer.echo(_("candidate.not_trusted"))


def _candidate_cleaned_output(report: dict[str, object]) -> str:
    outputs = cast(dict[str, object], report["outputs"])
    return str(outputs["transcript_cleaned"])


@candidate_app.command(
    "normalize",
    help=_("command.candidate.normalize.help"),
    epilog=_("candidate.normalize.epilog"),
    context_settings=HELP_CONTEXT_SETTINGS,
)
def candidate_normalize(
    input_path: Annotated[
        Path,
        typer.Option("--input", help=_("option.candidate_normalize_input.help")),
    ],
    output_dir: Annotated[
        Path | None,
        typer.Option("--output-dir", help=_("option.candidate_output_dir.help")),
    ] = None,
    target: Annotated[
        str,
        typer.Option("--to", help=_("option.candidate_normalize_target.help")),
    ] = "zh-Hans",
    output_name: Annotated[
        str | None,
        typer.Option("--output-name", help=_("option.candidate_normalize_output_name.help")),
    ] = None,
) -> None:
    """Create a script-normalized copy of candidate lyrics."""

    if target not in {"zh-Hans", "zh-Hant"}:
        typer.echo(_("candidate.normalize.invalid_target", target=target), err=True)
        raise typer.Exit(code=2)
    try:
        report = normalize_transcript_script(
            input_path,
            output_dir=output_dir,
            target=target,
            output_name=output_name,
        )
    except ScriptNormalizationError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(_("candidate.normalize.completed", path=report["output"]))
    typer.echo(_("candidate.normalize.source_preserved"))


@models_app.callback()
def models(ctx: typer.Context) -> None:
    """Show local model status when no model subcommand is selected."""
    if ctx.invoked_subcommand is None:
        models_status()


@models_app.command(
    "list",
    help=_("command.models.list.help"),
    context_settings=HELP_CONTEXT_SETTINGS,
)
def models_list() -> None:
    """List known model slots."""
    typer.echo(_("models.list.title"))
    for model in known_model_slots():
        display_name = _model_display_name(model.model_id, model.name)
        typer.echo(f"- {model.model_id}: {display_name} ({_('models.slot.status.placeholder')})")


@models_app.command(
    "status",
    help=_("command.models.status.help"),
    context_settings=HELP_CONTEXT_SETTINGS,
)
def models_status(
    language: Annotated[
        str,
        typer.Option("--language", help=_("option.language.help")),
    ] = "zh",
) -> None:
    """Show local model status."""
    typer.echo(_("models.status.title"))
    try:
        status = alignment_model_status(language)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    state = _("doctor.available") if status.available else _("doctor.not_available")
    typer.echo(f"- forced-aligner: {state}")
    typer.echo(f"  language: {status.language}")
    typer.echo(f"  model: {status.model_name}")
    typer.echo(f"  detail: {status.detail}")
    typer.echo("- vocal-separator: not required for v0.1.1")
    typer.echo(_("models.none_installed"))


@models_app.command(
    "pull",
    help=_("command.models.pull.help"),
    context_settings=HELP_CONTEXT_SETTINGS,
)
def models_pull(
    language: Annotated[
        str,
        typer.Option("--language", help=_("option.language.help")),
    ] = "zh",
    device: Annotated[
        DeviceStrategy,
        typer.Option("--device", help=_("option.device.help")),
    ] = DeviceStrategy.AUTO,
) -> None:
    """Explicitly download/preheat the local alignment model."""
    try:
        status = alignment_model_status(language)
        typer.echo(_("models.pull.notice"))
        typer.echo(f"language: {language}")
        typer.echo(f"model: {status.model_name}")
        typer.echo(f"source: {status.model_name}")
        typer.echo(_("models.pull.size_notice"))
        result = pull_alignment_model(language=language, device=device)
    except (RuntimeError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc

    typer.echo(_("models.pull.completed"))
    typer.echo(f"model: {result.model_name}")
    typer.echo(f"actual_alignment_device: {result.actual_device}")
    for warning in result.warnings:
        typer.echo(f"warning: {warning}")


@worker_app.command(
    "run",
    help=_("command.worker.run.help"),
    context_settings=HELP_CONTEXT_SETTINGS,
)
def worker_run(
    jobs_dir: Annotated[
        Path,
        typer.Option("--jobs-dir", help=_("option.worker_jobs_dir.help")),
    ] = Path("/jobs"),
    music_dir: Annotated[
        Path,
        typer.Option("--music-dir", help=_("option.worker_music_dir.help")),
    ] = Path("/music"),
    poll_interval_seconds: Annotated[
        float,
        typer.Option("--poll-interval-seconds", help=_("option.worker_poll_interval.help")),
    ] = 3.0,
    device: Annotated[
        DeviceStrategy,
        typer.Option("--device", help=_("option.device.help")),
    ] = DeviceStrategy.CPU,
    once: Annotated[
        bool,
        typer.Option("--once", help=_("option.worker_once.help")),
    ] = False,
    min_coverage: Annotated[
        float,
        typer.Option("--min-coverage", help=_("option.worker_min_coverage.help")),
    ] = 0.95,
    estimated_token_review_threshold: Annotated[
        int,
        typer.Option(
            "--estimated-token-review-threshold",
            help=_("option.worker_estimated_token_threshold.help"),
        ),
    ] = 0,
    running_timeout_seconds: Annotated[
        int,
        typer.Option("--running-timeout-seconds", help=_("option.worker_running_timeout.help")),
    ] = 3600,
) -> None:
    """Run the optional shared-directory worker."""

    run_worker(
        jobs_dir=jobs_dir,
        music_dir=music_dir,
        poll_interval_seconds=poll_interval_seconds,
        device=device,
        once=once,
        min_coverage=min_coverage,
        estimated_token_review_threshold=estimated_token_review_threshold,
        running_timeout_seconds=running_timeout_seconds,
    )


app.command(
    name="align",
    help=_("command.align.help"),
    epilog=_("align.epilog"),
    context_settings=HELP_CONTEXT_SETTINGS,
)(align_command)


if __name__ == "__main__":
    app()
