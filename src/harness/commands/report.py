"""Report scaffolding commands."""

from __future__ import annotations

import time
from pathlib import Path

import typer

from harness.commands.common import elapsed_ms, error_result, relative_display_path
from harness.commands.fs import resolve_workspace_path
from harness.config import HarnessSettings, get_settings
from harness.output import CommandResult, OutputEnvelope

app = typer.Typer(help="Report commands.", no_args_is_help=True)


def dispatch(
    args: list[str],
    settings: HarnessSettings | None = None,
    stdin: bytes = b"",
) -> CommandResult:
    """Source-of-truth parser for `run` path report commands."""
    _ = stdin
    active_settings: HarnessSettings = settings or get_settings()
    if not args:
        return _usage_error("report", "Usage: report <new|list|status> ...", ["report new <name>", "report list"])

    subcommand: str = args[0]
    if subcommand == "new":
        if len(args) != 2:
            return _usage_error("report new", "Usage: report new <name>", ["report list"])
        return create_report(args[1], settings=active_settings)
    if subcommand == "list":
        if len(args) != 1:
            return _usage_error("report list", "Usage: report list", ["report status <name>"])
        return list_reports(settings=active_settings)
    if subcommand == "status":
        if len(args) != 2:
            return _usage_error("report status", "Usage: report status <name>", ["report list"])
        return report_status(args[1], settings=active_settings)
    return _usage_error("report", f"Unknown report subcommand: {subcommand}", ["report new <name>", "report list"])


def create_report(name: str, *, settings: HarnessSettings | None = None) -> CommandResult:
    start: float = time.perf_counter()
    active_settings: HarnessSettings = settings or get_settings()
    try:
        report_root: Path = resolve_workspace_path(f"reports/{name}", active_settings)
        report_root.mkdir(parents=True, exist_ok=True)
        (report_root / "data").mkdir(exist_ok=True)
        (report_root / "outline.md").write_text(f"# {name}\n\n## Thesis\n\n## Questions\n\n## Sources\n", encoding="utf-8")
        (report_root / "notes.md").write_text(f"# {name} Notes\n\n", encoding="utf-8")
    except Exception as exc:
        return error_result(
            f"What went wrong: failed to create report scaffold `{name}`: {exc}\n"
            "What to do instead: use a workspace-safe report name and ensure the workspace is writable.\n"
            "Available alternatives: `report list`, `ls reports`",
            start,
        )

    relative_root: str = relative_display_path(report_root, active_settings.ensure_workspace_root())
    return CommandResult.from_text(f"Created report scaffold at {relative_root}", duration_ms=elapsed_ms(start))


def list_reports(*, settings: HarnessSettings | None = None) -> CommandResult:
    start: float = time.perf_counter()
    active_settings: HarnessSettings = settings or get_settings()
    reports_root: Path = resolve_workspace_path("reports", active_settings)
    reports_root.mkdir(parents=True, exist_ok=True)
    entries: list[str] = [child.name for child in sorted(reports_root.iterdir()) if child.is_dir()]
    return CommandResult.from_text("\n".join(entries) if entries else "(no reports)", duration_ms=elapsed_ms(start))


def report_status(name: str, *, settings: HarnessSettings | None = None) -> CommandResult:
    start: float = time.perf_counter()
    active_settings: HarnessSettings = settings or get_settings()
    report_root: Path = resolve_workspace_path(f"reports/{name}", active_settings)
    if not report_root.exists():
        return error_result(
            f"What went wrong: report `{name}` does not exist.\n"
            "What to do instead: create it with `report new <name>` or inspect available reports with `report list`.\n"
            "Available alternatives: `report new <name>`, `report list`",
            start,
        )

    lines: list[str] = [f"report: {name}"]
    for child in sorted(report_root.rglob("*")):
        relative: str = relative_display_path(child, report_root)
        if child.is_dir():
            lines.append(f"{relative}/")
            continue
        content: str = child.read_text(encoding="utf-8", errors="replace") if child.suffix in {".md", ".txt", ".csv"} else ""
        word_count: int = len(content.split()) if content else 0
        lines.append(f"{relative} words={word_count}")
    return CommandResult.from_text("\n".join(lines), duration_ms=elapsed_ms(start))


@app.command("new")
def new_command(name: str = typer.Argument(..., help="Report folder name.")) -> None:
    """Create a new report scaffold."""
    _print(create_report(name))


@app.command("list")
def list_command() -> None:
    """List reports under the workspace reports directory."""
    _print(list_reports())


@app.command("status")
def status_command(name: str = typer.Argument(..., help="Report folder name.")) -> None:
    """Show report structure and word counts."""
    _print(report_status(name))


def _usage_error(command: str, usage: str, alternatives: list[str]) -> CommandResult:
    return CommandResult.from_text(
        "",
        stderr=(
            f"Invalid invocation for `{command}`.\n"
            f"What to do instead: {usage}\n"
            f"Available alternatives: {', '.join(alternatives)}"
        ),
        exit_code=1,
    )


def _print(result: CommandResult) -> None:
    envelope = OutputEnvelope.from_result(result, workspace_root=get_settings().ensure_workspace_root())
    typer.echo(envelope.render())
