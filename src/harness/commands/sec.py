"""SEC EDGAR commands."""

from __future__ import annotations

import time

import typer
from edgar import Company

from harness.commands.common import (
    dataframe_to_markdown,
    elapsed_ms,
    error_result,
    retry_call,
    should_retry_network_error,
)
from harness.config import HarnessSettings, get_settings
from harness.output import CommandResult, OutputEnvelope
from minerva.sec import get_10k_items, get_13f_comparison

app = typer.Typer(help="SEC filing tools.", no_args_is_help=True)


def dispatch(
    args: list[str],
    settings: HarnessSettings | None = None,
    stdin: bytes = b"",
) -> CommandResult:
    """Source-of-truth parser for `run` path SEC commands."""
    _ = stdin
    active_settings: HarnessSettings = settings or get_settings()
    if not args:
        return _usage_error("sec", "Usage: sec <10k|13f|financials> ...", ["sec 10k MSFT", "sec 13f 1067983"])

    subcommand: str = args[0]
    if subcommand == "10k":
        if len(args) < 2:
            return _usage_error("sec 10k", "Usage: sec 10k <ticker> [--items 1,1A,7]", ["sec financials <ticker>"])
        ticker: str = args[1]
        items: list[str] | None = None
        if len(args) > 2:
            if len(args) != 4 or args[2] != "--items":
                return _usage_error("sec 10k", "Usage: sec 10k <ticker> [--items 1,1A,7]", ["sec financials <ticker>"])
            items = _parse_csv_values(args[3])
        return get_10k_command(ticker, items=items, settings=active_settings)

    if subcommand == "13f":
        if len(args) != 2:
            return _usage_error("sec 13f", "Usage: sec 13f <cik>", ["sec 10k <ticker>"])
        return get_13f_command(args[1], settings=active_settings)

    if subcommand == "financials":
        if len(args) < 2:
            return _usage_error(
                "sec financials",
                "Usage: sec financials <ticker> [--periods 5] [--type income|balance|cash]",
                ["sec 10k <ticker>", "sec 13f <cik>"],
            )
        ticker = args[1]
        periods: int = 5
        statement_type: str = "income"
        index: int = 2
        while index < len(args):
            token: str = args[index]
            if token == "--periods" and index + 1 < len(args):
                periods = int(args[index + 1])
                index += 2
                continue
            if token == "--type" and index + 1 < len(args):
                statement_type = args[index + 1]
                index += 2
                continue
            return _usage_error(
                "sec financials",
                "Usage: sec financials <ticker> [--periods 5] [--type income|balance|cash]",
                ["sec 10k <ticker>", "sec 13f <cik>"],
            )
        return get_financials_command(ticker, periods=periods, statement_type=statement_type, settings=active_settings)

    return _usage_error("sec", f"Unknown sec subcommand: {subcommand}", ["sec 10k <ticker>", "sec 13f <cik>"])


def get_10k_command(
    ticker: str,
    *,
    items: list[str] | None = None,
    settings: HarnessSettings | None = None,
) -> CommandResult:
    """Fetch selected 10-K item sections."""
    start: float = time.perf_counter()
    _ = settings or get_settings()
    try:
        item_map: dict[str, str] = retry_call(
            lambda: get_10k_items(ticker, items or ["1", "1A", "7"]),
            should_retry=should_retry_network_error,
        )
    except Exception as exc:
        return error_result(
            f"What went wrong: failed to fetch 10-K items for {ticker}: {exc}\n"
            "What to do instead: verify the ticker and item list, then retry.\n"
            "Available alternatives: `sec financials <ticker>`, `web search <company> 10-K`",
            start,
        )

    lines: list[str] = []
    for item_number, text in item_map.items():
        body: str = text.strip() or "(no text returned)"
        lines.append(f"## Item {item_number}\n\n{body}")
    return CommandResult.from_text("\n\n".join(lines), duration_ms=elapsed_ms(start))


def get_13f_command(cik: str, *, settings: HarnessSettings | None = None) -> CommandResult:
    """Fetch and format a 13-F comparison."""
    start: float = time.perf_counter()
    _ = settings or get_settings()
    try:
        comparison = retry_call(
            lambda: get_13f_comparison(cik),
            should_retry=should_retry_network_error,
        )
    except Exception as exc:
        return error_result(
            f"What went wrong: failed to compare 13-F filings for {cik}: {exc}\n"
            "What to do instead: verify the CIK and ensure at least two 13-F filings exist.\n"
            "Available alternatives: `sec 10k <ticker>`, `web search <fund> 13F`",
            start,
        )

    sections: list[str] = []
    summary_lines: list[str] = [
        f"current positions: {len(comparison['current'])}",
        f"previous positions: {len(comparison['previous'])}",
        f"new positions: {len(comparison['new'])}",
        f"exited positions: {len(comparison['exited'])}",
        f"increased positions: {len(comparison['increased'])}",
        f"decreased positions: {len(comparison['decreased'])}",
    ]
    sections.append("\n".join(summary_lines))
    for key in ["new", "exited", "increased", "decreased"]:
        sections.append(f"## {key.title()}\n\n{dataframe_to_markdown(comparison[key])}")
    return CommandResult.from_text("\n\n".join(sections), duration_ms=elapsed_ms(start))


def get_financials_command(
    ticker: str,
    *,
    periods: int = 5,
    statement_type: str = "income",
    settings: HarnessSettings | None = None,
) -> CommandResult:
    """Fetch annual financial statements with edgartools."""
    start: float = time.perf_counter()
    _ = settings or get_settings()
    statement_type = statement_type.lower()
    try:
        frame = retry_call(
            lambda: _fetch_financials_frame(ticker, periods=periods, statement_type=statement_type),
            should_retry=should_retry_network_error,
        )
    except Exception as exc:
        return error_result(
            f"What went wrong: failed to fetch {statement_type} financials for {ticker}: {exc}\n"
            "What to do instead: use `--type income`, `--type balance`, or `--type cash` with a valid ticker.\n"
            "Available alternatives: `sec 10k <ticker>`, `web search <ticker> annual report`",
            start,
        )

    if hasattr(frame, "reset_index"):
        frame = frame.reset_index()
    body: str = f"# {ticker.upper()} {statement_type.title()} Financials\n\n{dataframe_to_markdown(frame, max_rows=40)}"
    return CommandResult.from_text(body, duration_ms=elapsed_ms(start))


@app.command("10k")
def ten_k_command(
    ticker: str = typer.Argument(..., help="Ticker or CIK."),
    items: str = typer.Option("1,1A,7", "--items", help="Comma-separated item numbers."),
) -> None:
    """Fetch selected sections from the latest 10-K."""
    _print(get_10k_command(ticker, items=_parse_csv_values(items)))


@app.command("13f")
def thirteen_f_command(cik: str = typer.Argument(..., help="Manager CIK.")) -> None:
    """Compare the latest two 13-F filings."""
    _print(get_13f_command(cik))


@app.command("financials")
def financials_command(
    ticker: str = typer.Argument(..., help="Ticker."),
    periods: int = typer.Option(5, "--periods", min=1, help="Number of annual periods."),
    statement_type: str = typer.Option("income", "--type", help="income, balance, or cash"),
) -> None:
    """Fetch annual financial statement data."""
    _print(get_financials_command(ticker, periods=periods, statement_type=statement_type))


def _parse_csv_values(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def _fetch_financials_frame(ticker: str, *, periods: int, statement_type: str):
    company: Company = Company(ticker)
    company.get_filings(form="10-K").latest(periods)
    if statement_type == "income":
        return company.income_statement(periods=periods, period="annual", as_dataframe=True)
    if statement_type == "balance":
        return company.balance_sheet(periods=periods, period="annual", as_dataframe=True)
    if statement_type == "cash":
        return company.cashflow_statement(periods=periods, period="annual", as_dataframe=True)
    raise ValueError(f"unknown financial statement type: {statement_type}")


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
