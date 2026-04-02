"""Memory commands."""

from __future__ import annotations

import time

import typer

from harness.commands.common import elapsed_ms, error_result
from harness.config import HarnessSettings, get_settings
from harness.memory import forget_fact, recent_facts, search_facts, store_fact
from harness.output import CommandResult, OutputEnvelope

app = typer.Typer(help="Memory commands.", no_args_is_help=True)


def dispatch(args: list[str], settings: HarnessSettings | None = None) -> CommandResult:
    active_settings: HarnessSettings = settings or get_settings()
    if not args:
        return _usage_error(
            "memory",
            "Usage: memory <store|facts|forget|search|recent> ...",
            ["memory store <text>", "memory facts"],
        )

    subcommand: str = args[0]
    if subcommand == "store":
        if len(args) < 2:
            return _usage_error("memory store", "Usage: memory store <text>", ["memory facts", "memory search <query>"])
        return store_memory(" ".join(args[1:]), settings=active_settings)
    if subcommand == "facts":
        if len(args) != 1:
            return _usage_error("memory facts", "Usage: memory facts", ["memory recent", "memory search <query>"])
        return list_memory(settings=active_settings)
    if subcommand == "forget":
        if len(args) != 2:
            return _usage_error("memory forget", "Usage: memory forget <id>", ["memory facts"])
        return forget_memory(int(args[1]), settings=active_settings)
    if subcommand == "search":
        if len(args) < 2:
            return _usage_error("memory search", "Usage: memory search <query>", ["memory facts"])
        return search_memory(" ".join(args[1:]), settings=active_settings)
    if subcommand == "recent":
        if len(args) > 2:
            return _usage_error("memory recent", "Usage: memory recent [N]", ["memory facts"])
        limit: int = int(args[1]) if len(args) == 2 else 10
        return recent_memory(limit=limit, settings=active_settings)
    return _usage_error("memory", f"Unknown memory subcommand: {subcommand}", ["memory store <text>", "memory facts"])


def store_memory(text: str, *, settings: HarnessSettings | None = None) -> CommandResult:
    start: float = time.perf_counter()
    try:
        fact_id: int = store_fact(text, settings=settings)
    except Exception as exc:
        return error_result(
            f"What went wrong: failed to store memory: {exc}\n"
            "What to do instead: provide a non-empty text fact and ensure the workspace is writable.\n"
            "Available alternatives: `memory facts`, `memory search <query>`",
            start,
        )
    return CommandResult.from_text(f"Stored fact {fact_id}", duration_ms=elapsed_ms(start))


def list_memory(*, settings: HarnessSettings | None = None) -> CommandResult:
    start: float = time.perf_counter()
    facts = recent_facts(limit=10_000, settings=settings)
    body: str = _format_facts(facts)
    return CommandResult.from_text(body, duration_ms=elapsed_ms(start))


def forget_memory(fact_id: int, *, settings: HarnessSettings | None = None) -> CommandResult:
    start: float = time.perf_counter()
    deleted: bool = forget_fact(fact_id, settings=settings)
    if not deleted:
        return error_result(
            f"What went wrong: no fact with id {fact_id} exists.\n"
            "What to do instead: inspect current ids with `memory facts` and retry.\n"
            "Available alternatives: `memory facts`, `memory recent`",
            start,
        )
    return CommandResult.from_text(f"Forgot fact {fact_id}", duration_ms=elapsed_ms(start))


def search_memory(query: str, *, settings: HarnessSettings | None = None) -> CommandResult:
    start: float = time.perf_counter()
    facts = search_facts(query, settings=settings)
    return CommandResult.from_text(_format_facts(facts), duration_ms=elapsed_ms(start))


def recent_memory(limit: int = 10, *, settings: HarnessSettings | None = None) -> CommandResult:
    start: float = time.perf_counter()
    facts = recent_facts(limit=limit, settings=settings)
    return CommandResult.from_text(_format_facts(facts), duration_ms=elapsed_ms(start))


@app.command("store")
def store_command(text: str = typer.Argument(..., help="Fact text to store.")) -> None:
    """Store a memory fact."""
    _print(store_memory(text))


@app.command("facts")
def facts_command() -> None:
    """List all stored facts."""
    _print(list_memory())


@app.command("forget")
def forget_command(fact_id: int = typer.Argument(..., help="Fact id to delete.")) -> None:
    """Delete a fact by id."""
    _print(forget_memory(fact_id))


@app.command("search")
def search_command(query: str = typer.Argument(..., help="Query text.")) -> None:
    """Search stored facts."""
    _print(search_memory(query))


@app.command("recent")
def recent_command(limit: int = typer.Argument(10, help="How many recent facts to show.")) -> None:
    """Show recent facts."""
    _print(recent_memory(limit))


def _format_facts(facts: list[dict]) -> str:
    if not facts:
        return "(no facts)"
    return "\n".join(f"[{fact['id']}] {fact['created_at']} {fact['content']}" for fact in facts)


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
