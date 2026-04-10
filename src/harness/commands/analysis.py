"""Analysis workflow commands built on deterministic disk state."""

from __future__ import annotations

import time

import typer

from harness.commands.common import abort_with_help, elapsed_ms, error_result, parse_flag_args
from harness.config import HarnessSettings, get_settings
from harness.output import CommandResult, OutputEnvelope
from harness.workflows.analysis.context import run_context
from harness.workflows.analysis.status import run_status
from harness.workflows.evidence.paths import resolve_company_root

ANALYSIS_HELP = (
    "Analysis workflow status and context packaging commands.\n\n"
    "Examples:\n"
    "  minerva analysis status --root hard-disk/reports/00-companies/12-robinhood\n"
    "  minerva analysis context --root hard-disk/reports/00-companies/12-robinhood --profile default\n"
)

app = typer.Typer(help=ANALYSIS_HELP, no_args_is_help=True)


def dispatch(args: list[str], settings: HarnessSettings | None = None, stdin: bytes = b"") -> CommandResult:
    """Dispatch analysis workflow commands for `minerva run`."""
    _ = settings
    _ = stdin
    if not args:
        return CommandResult.from_text("", stderr=_usage_error("no `analysis` subcommand was provided", "choose `status` or `context`", ["`analysis status --root ...`", "`analysis context --root ... --profile default`"], ANALYSIS_HELP), exit_code=1)

    subcommand = args[0]
    try:
        if subcommand == "status":
            parsed = parse_flag_args(args[1:])
            return status_command(root=str(parsed["root"]))
        if subcommand == "context":
            parsed = parse_flag_args(args[1:])
            return context_command(root=str(parsed["root"]), profile=str(parsed.get("profile", "default")))
    except KeyError as exc:
        return CommandResult.from_text("", stderr=f"missing required flag: {exc}", exit_code=1)
    except ValueError as exc:
        return CommandResult.from_text("", stderr=str(exc), exit_code=1)

    return CommandResult.from_text("", stderr=_usage_error(f"unknown `analysis` subcommand `{subcommand}`", "choose `status` or `context`", ["`analysis status --root ...`", "`analysis context --root ... --profile default`"], ANALYSIS_HELP), exit_code=1)


def status_command(*, root: str) -> CommandResult:
    """Compute the current analysis workflow stage."""
    start = time.perf_counter()
    try:
        paths = resolve_company_root(root)
        status_payload = run_status(paths)
    except Exception as exc:
        return error_result(
            f"failed to compute analysis status: {exc}",
            "verify the workflow root and retry",
            ["`minerva analysis status --root hard-disk/reports/00-companies/12-robinhood`"],
            start,
        )
    body = "\n".join(
        [
            f"stage: {status_payload['stage']}",
            f"next_step: {status_payload['next_step']}",
            f"status_json: {paths.status_json.relative_to(paths.root)}",
        ]
    )
    return CommandResult.from_text(body, duration_ms=elapsed_ms(start))


def context_command(*, root: str, profile: str) -> CommandResult:
    """Build section bundles from extracted evidence outputs."""
    start = time.perf_counter()
    try:
        paths = resolve_company_root(root)
        manifest = run_context(paths, profile_name=profile)
    except Exception as exc:
        return error_result(
            f"failed to build analysis context: {exc}",
            "verify the workflow root, extracted artifacts, and context profile, then retry",
            ["`minerva analysis context --root hard-disk/reports/00-companies/12-robinhood --profile default`"],
            start,
        )
    body = "\n".join(
        [
            f"bundle_count: {len(manifest['bundles'])}",
            f"estimated_tokens: {manifest['estimated_tokens']}",
            f"context_manifest_json: {paths.context_manifest_json.relative_to(paths.root)}",
        ]
    )
    return CommandResult.from_text(body, duration_ms=elapsed_ms(start))


@app.command("status", help="Summarize the current deep-dive workflow stage.")
def status_cli_command(
    ctx: typer.Context,
    root: str | None = typer.Option(None, "--root", help="Company evidence root."),
) -> None:
    if not root:
        abort_with_help(
            ctx,
            what_went_wrong="missing required arguments for `analysis status`",
            what_to_do="pass `--root`",
            alternatives=["`minerva analysis status --root hard-disk/reports/00-companies/12-robinhood`"],
        )
    _print(status_command(root=root))


@app.command("context", help="Build analysis section bundles from extracted artifacts.")
def context_cli_command(
    ctx: typer.Context,
    root: str | None = typer.Option(None, "--root", help="Company evidence root."),
    profile: str = typer.Option("default", "--profile", help="Context profile name."),
) -> None:
    if not root:
        abort_with_help(
            ctx,
            what_went_wrong="missing required arguments for `analysis context`",
            what_to_do="pass `--root`",
            alternatives=["`minerva analysis context --root hard-disk/reports/00-companies/12-robinhood --profile default`"],
        )
    _print(context_command(root=root, profile=profile))


def _usage_error(what: str, what_to_do: str, alternatives: list[str], help_text: str) -> str:
    return "\n".join(
        [
            f"What went wrong: {what}",
            f"What to do instead: {what_to_do}",
            f"Available alternatives: {', '.join(alternatives)}",
            "",
            help_text.rstrip(),
        ]
    )


def _print(result: CommandResult) -> None:
    envelope = OutputEnvelope.from_result(result, workspace_root=get_settings().ensure_workspace_root())
    typer.echo(envelope.render())
