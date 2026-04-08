"""SEC EDGAR commands."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import typer

from harness.commands.common import (
    abort_with_help,
    dataframe_to_markdown,
    elapsed_ms,
    error_result,
    maybe_export_text,
    parse_flag_args,
    relative_display_path,
    resolve_path,
    retry_call,
    should_retry_network_error,
)
from harness.config import HarnessSettings, get_settings
from harness.output import CommandResult, OutputEnvelope

SEC_HELP = (
    "SEC EDGAR filing tools.\n\n"
    "Examples:\n"
    "  minerva sec 10k AAPL --items 1,1A,7\n"
    "  minerva sec financials MSFT --type income --periods 5\n"
    "  minerva sec download AAPL --form 10-K --format markdown\n"
    "  minerva sec bulk-download AAPL MSFT --output ./comp-analysis\n"
)

app = typer.Typer(help=SEC_HELP, no_args_is_help=True)


def Company(*args, **kwargs):
    from edgar import Company as EdgarCompany

    return EdgarCompany(*args, **kwargs)


def set_identity(*args, **kwargs) -> None:
    from edgar import set_identity as edgar_set_identity

    edgar_set_identity(*args, **kwargs)


def get_10k_items(*args, **kwargs):
    from minerva.sec import get_10k_items as minerva_get_10k_items

    return minerva_get_10k_items(*args, **kwargs)


def get_13f_comparison(*args, **kwargs):
    from minerva.sec import get_13f_comparison as minerva_get_13f_comparison

    return minerva_get_13f_comparison(*args, **kwargs)


def dispatch(
    args: list[str],
    settings: HarnessSettings | None = None,
    stdin: bytes = b"",
) -> CommandResult:
    """Source-of-truth parser for `run` path SEC commands."""
    _ = stdin
    active_settings: HarnessSettings = settings or get_settings()
    if not args:
        return CommandResult.from_text(
            "",
            stderr=_usage_error(
                "no `sec` subcommand was provided",
                "choose one of the supported SEC subcommands",
                ["`sec 10k AAPL --items 1,1A,7`", "`sec bulk-download AAPL`"],
                SEC_HELP,
            ),
            exit_code=1,
        )

    subcommand: str = args[0]
    try:
        if subcommand == "10k":
            if len(args) < 2:
                return _dispatch_help("10k", ["`sec financials MSFT --type income`"])
            parsed = parse_flag_args(args[2:])
            items = str(parsed.get("items", "1,1A,7"))
            return get_10k_command(str(args[1]), items=_parse_csv_values(items), settings=active_settings)

        if subcommand == "13f":
            if len(args) != 2:
                return _dispatch_help("13f", ["`sec 10k BRK-B --items 1A`"])
            return get_13f_command(str(args[1]), settings=active_settings)

        if subcommand == "financials":
            if len(args) < 2:
                return _dispatch_help("financials", ["`sec financials MSFT --type income --periods 5`"])
            parsed = parse_flag_args(args[2:])
            return get_financials_command(
                str(args[1]),
                periods=int(parsed.get("periods", 5)),
                statement_type=str(parsed.get("type", "income")),
                settings=active_settings,
            )

        if subcommand == "download":
            if len(args) < 2:
                return _dispatch_help("download", ["`sec download AAPL --form 10-K --format markdown`"])
            parsed = parse_flag_args(args[2:])
            return download_filing_command(
                str(args[1]),
                form=str(parsed.get("form", "10-K")),
                file_format=str(parsed.get("format", "html")),
                output_path=str(parsed["output"]) if "output" in parsed else None,
                settings=active_settings,
            )

        if subcommand == "bulk-download":
            parsed_args: list[str] = []
            tickers: list[str] = []
            index = 1
            while index < len(args):
                token = args[index]
                if token.startswith("--"):
                    parsed_args.extend(args[index : index + 2])
                    index += 2
                    continue
                tickers.append(token)
                index += 1
            parsed = parse_flag_args(parsed_args)
            if not tickers:
                return _dispatch_help("bulk-download", ["`sec bulk-download AAPL MSFT --output ./comp-analysis`"])
            return bulk_download_command(
                tickers=tickers,
                output_dir=str(parsed["output"]) if "output" in parsed else None,
                annual=int(parsed.get("annual", 5)),
                quarters=int(parsed.get("quarters", 4)),
                earnings=int(parsed.get("earnings", 4)),
                include_financials=_as_bool(parsed.get("financials", True)),
                settings=active_settings,
            )
    except ValueError as exc:
        return CommandResult.from_text("", stderr=str(exc), exit_code=1)

    return CommandResult.from_text(
        "",
        stderr=_usage_error(
            f"unknown `sec` subcommand `{subcommand}`",
            "choose one of the supported SEC subcommands",
            ["`sec 10k AAPL --items 7`", "`sec download AAPL --form 10-K`"],
            SEC_HELP,
        ),
        exit_code=1,
    )


def get_10k_command(
    ticker: str,
    *,
    items: list[str] | None = None,
    settings: HarnessSettings | None = None,
) -> CommandResult:
    """Fetch selected 10-K item sections."""
    start: float = time.perf_counter()
    active_settings: HarnessSettings = settings or get_settings()
    identity_error = _configure_edgar(active_settings)
    if identity_error:
        return error_result(identity_error, "set EDGAR_IDENTITY and retry", ["`export EDGAR_IDENTITY='Minerva Research name@email.com'`"], start)
    try:
        item_map: dict[str, str] = retry_call(
            lambda: get_10k_items(ticker, items or ["1", "1A", "7"]),
            should_retry=should_retry_network_error,
        )
    except Exception as exc:
        return error_result(
            f"failed to fetch 10-K items for {ticker}: {exc}",
            "verify the ticker and item list, then retry",
            ["`sec financials {ticker} --type income`".format(ticker=ticker), "`sec download {ticker} --form 10-K --format markdown`".format(ticker=ticker)],
            start,
        )

    lines: list[str] = []
    for item_number, text in item_map.items():
        lines.append(f"## Item {item_number}\n\n{(text or '').strip() or '(no text returned)'}")
    return CommandResult.from_text("\n\n".join(lines), duration_ms=elapsed_ms(start))


def get_13f_command(cik: str, *, settings: HarnessSettings | None = None) -> CommandResult:
    """Fetch and format a 13-F comparison."""
    start: float = time.perf_counter()
    active_settings: HarnessSettings = settings or get_settings()
    identity_error = _configure_edgar(active_settings)
    if identity_error:
        return error_result(identity_error, "set EDGAR_IDENTITY and retry", ["`export EDGAR_IDENTITY='Minerva Research name@email.com'`"], start)
    try:
        comparison = retry_call(lambda: get_13f_comparison(cik), should_retry=should_retry_network_error)
    except Exception as exc:
        return error_result(
            f"failed to compare 13-F filings for {cik}: {exc}",
            "verify the manager CIK and ensure at least two 13F-HR filings exist",
            ["`sec 10k BRK-B --items 1A`", "`sec download {cik} --form 13F-HR`".format(cik=cik)],
            start,
        )

    summary_lines: list[str] = [
        f"current positions: {len(comparison['current'])}",
        f"previous positions: {len(comparison['previous'])}",
        f"new positions: {len(comparison['new'])}",
        f"exited positions: {len(comparison['exited'])}",
        f"increased positions: {len(comparison['increased'])}",
        f"decreased positions: {len(comparison['decreased'])}",
    ]
    sections: list[str] = ["\n".join(summary_lines)]
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
    active_settings: HarnessSettings = settings or get_settings()
    identity_error = _configure_edgar(active_settings)
    if identity_error:
        return error_result(identity_error, "set EDGAR_IDENTITY and retry", ["`export EDGAR_IDENTITY='Minerva Research name@email.com'`"], start)
    try:
        frame = retry_call(
            lambda: _fetch_financials_frame(ticker, periods=periods, statement_type=statement_type.lower()),
            should_retry=should_retry_network_error,
        )
    except Exception as exc:
        return error_result(
            f"failed to fetch {statement_type} financials for {ticker}: {exc}",
            "use `--type income`, `--type balance`, or `--type cash` with a valid ticker",
            ["`sec 10k {ticker} --items 7`".format(ticker=ticker), "`sec download {ticker} --form 10-K --format markdown`".format(ticker=ticker)],
            start,
        )

    frame = frame.reset_index() if hasattr(frame, "reset_index") else frame
    body: str = f"# {ticker.upper()} {statement_type.title()} Financials\n\n{dataframe_to_markdown(frame, max_rows=40)}"
    return CommandResult.from_text(body, duration_ms=elapsed_ms(start))


def download_filing_command(
    ticker: str,
    *,
    form: str = "10-K",
    file_format: str = "html",
    output_path: str | None = None,
    settings: HarnessSettings | None = None,
) -> CommandResult:
    """Download a single filing to disk."""
    start: float = time.perf_counter()
    active_settings = settings or get_settings()
    identity_error = _configure_edgar(active_settings)
    if identity_error:
        return error_result(identity_error, "set EDGAR_IDENTITY and retry", ["`export EDGAR_IDENTITY='Minerva Research name@email.com'`"], start)

    try:
        filing = retry_call(lambda: _latest_filing(Company(ticker), form=form), should_retry=should_retry_network_error)
        filing_date: str = str(getattr(filing, "filing_date", getattr(filing, "date", "latest")))
        accession: str = str(getattr(filing, "accession_number", "unknown"))
        ext: str = "html" if file_format == "html" else "md"
        target: Path = resolve_path(output_path or f"{ticker}-{form}-{filing_date}.{ext}")
        target.parent.mkdir(parents=True, exist_ok=True)
        _save_filing(filing, target, file_format=file_format)
    except Exception as exc:
        return error_result(
            f"failed to download {form} for {ticker}: {exc}",
            "verify the ticker, form, and output path, then retry",
            ["`sec 10k {ticker} --items 1,1A,7`".format(ticker=ticker), "`sec financials {ticker} --type income`".format(ticker=ticker)],
            start,
        )

    body = "\n".join(
        [
            f"saved_to: {relative_display_path(target)}",
            f"form: {form}",
            f"filing_date: {filing_date}",
            f"accession_number: {accession}",
        ]
    )
    return CommandResult.from_text(body, duration_ms=elapsed_ms(start))


def bulk_download_command(
    *,
    tickers: list[str],
    output_dir: str | None = None,
    annual: int = 5,
    quarters: int = 4,
    earnings: int = 4,
    include_financials: bool = True,
    settings: HarnessSettings | None = None,
) -> CommandResult:
    """Download a filing library for one or more tickers."""
    start: float = time.perf_counter()
    active_settings = settings or get_settings()
    identity_error = _configure_edgar(active_settings)
    if identity_error:
        return error_result(identity_error, "set EDGAR_IDENTITY and retry", ["`export EDGAR_IDENTITY='Minerva Research name@email.com'`"], start)

    base_output = resolve_path(output_dir or ".")
    lines: list[str] = []
    try:
        for ticker in tickers:
            summary = _bulk_download_one(
                ticker=ticker,
                base_output=base_output,
                annual=annual,
                quarters=quarters,
                earnings=earnings,
                include_financials=include_financials,
            )
            lines.extend(summary)
            lines.append("")
    except Exception as exc:
        return error_result(
            f"bulk download failed: {exc}",
            "retry with one ticker first or reduce the requested filing counts",
            ["`sec bulk-download AAPL`", "`sec download AAPL --form 10-K --format markdown`"],
            start,
        )
    return CommandResult.from_text("\n".join(line for line in lines if line is not None).rstrip(), duration_ms=elapsed_ms(start))


@app.command("10k", help="Fetch selected sections from the most recent 10-K.\n\nExample:\n  minerva sec 10k AAPL --items 1,1A,7")
def ten_k_command(
    ctx: typer.Context,
    ticker: str | None = typer.Argument(None, help="Company ticker or CIK."),
    items: str = typer.Option("1,1A,7", "--items", help="Comma-separated 10-K item numbers."),
) -> None:
    if not ticker:
        abort_with_help(
            ctx,
            what_went_wrong="no ticker or CIK was provided for `sec 10k`",
            what_to_do="pass a ticker like `AAPL` or a numeric CIK",
            alternatives=["`minerva sec 10k AAPL --items 1,1A,7`", "`minerva sec financials AAPL --type income`"],
        )
    _print(get_10k_command(ticker, items=_parse_csv_values(items)))


@app.command("13f", help="Compare the two most recent 13F-HR filings.\n\nExample:\n  minerva sec 13f 1067983")
def thirteen_f_command(
    ctx: typer.Context,
    cik: str | None = typer.Argument(None, help="Manager CIK number."),
) -> None:
    if not cik:
        abort_with_help(
            ctx,
            what_went_wrong="no manager CIK was provided for `sec 13f`",
            what_to_do="pass a manager CIK such as `1067983`",
            alternatives=["`minerva sec 13f 1067983`", "`minerva sec 10k BRK-B --items 1A`"],
        )
    _print(get_13f_command(cik))


@app.command("financials", help="Fetch annual financial statements.\n\nExample:\n  minerva sec financials MSFT --type income --periods 5")
def financials_command(
    ctx: typer.Context,
    ticker: str | None = typer.Argument(None, help="Company ticker."),
    periods: int = typer.Option(5, "--periods", min=1, help="Number of annual periods."),
    statement_type: str = typer.Option("income", "--type", help="Statement type: income, balance, or cash."),
) -> None:
    if not ticker:
        abort_with_help(
            ctx,
            what_went_wrong="no ticker was provided for `sec financials`",
            what_to_do="pass a ticker and optional `--type` / `--periods` values",
            alternatives=["`minerva sec financials MSFT --type income`", "`minerva sec 10k MSFT --items 7`"],
        )
    _print(get_financials_command(ticker, periods=periods, statement_type=statement_type))


@app.command("download", help="Download a filing as HTML or markdown.\n\nExample:\n  minerva sec download AAPL --form 10-K --format markdown")
def download_command(
    ctx: typer.Context,
    ticker: str | None = typer.Argument(None, help="Company ticker or CIK."),
    form: str = typer.Option("10-K", "--form", help="Filing form type."),
    file_format: str = typer.Option("html", "--format", help="Output format: html or markdown."),
    output: str | None = typer.Option(None, "--output", help="Output file path."),
) -> None:
    if not ticker:
        abort_with_help(
            ctx,
            what_went_wrong="no ticker or CIK was provided for `sec download`",
            what_to_do="pass a ticker and optional form/format arguments",
            alternatives=["`minerva sec download AAPL --form 10-K --format markdown`", "`minerva sec bulk-download AAPL`"],
        )
    _print(download_filing_command(ticker, form=form, file_format=file_format, output_path=output))


@app.command("bulk-download", help="Download a filing library for one or more companies.\n\nExample:\n  minerva sec bulk-download AAPL MSFT --output ./comp-analysis")
def bulk_download_cli_command(
    ctx: typer.Context,
    tickers: list[str] = typer.Argument(None, help="One or more company tickers."),
    output: str | None = typer.Option(None, "--output", help="Output directory."),
    annual: int = typer.Option(5, "--annual", min=0, help="Number of annual 10-K filings."),
    quarters: int = typer.Option(4, "--quarters", min=0, help="Number of quarterly 10-Q filings."),
    earnings: int = typer.Option(4, "--earnings", min=0, help="Number of earnings releases."),
    financials: bool = typer.Option(True, "--financials/--no-financials", help="Include markdown financial statement tables."),
) -> None:
    if not tickers:
        abort_with_help(
            ctx,
            what_went_wrong="no tickers were provided for `sec bulk-download`",
            what_to_do="pass one or more tickers after the subcommand",
            alternatives=["`minerva sec bulk-download AAPL`", "`minerva sec bulk-download AAPL MSFT --output ./comp-analysis`"],
        )
    _print(
        bulk_download_command(
            tickers=tickers,
            output_dir=output,
            annual=annual,
            quarters=quarters,
            earnings=earnings,
            include_financials=financials,
        )
    )


def _configure_edgar(settings: HarnessSettings) -> str | None:
    if not settings.edgar_identity:
        return "EDGAR_IDENTITY is required for SEC commands"
    set_identity(settings.edgar_identity)
    return None


def _parse_csv_values(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def _fetch_financials_frame(ticker: str, *, periods: int, statement_type: str):
    company = Company(ticker)
    if statement_type == "income":
        return company.income_statement(periods=periods, period="annual", as_dataframe=True)
    if statement_type == "balance":
        return company.balance_sheet(periods=periods, period="annual", as_dataframe=True)
    if statement_type == "cash":
        return company.cashflow_statement(periods=periods, period="annual", as_dataframe=True)
    raise ValueError(f"unknown financial statement type: {statement_type}")


def _latest_filing(company: Any, *, form: str) -> Any:
    filing_list = _list_filings(company, form=form, limit=1)
    if not filing_list:
        raise ValueError(f"no filings found for form {form}")
    return filing_list[0]


def _save_filing(filing: Any, target: Path, *, file_format: str) -> None:
    normalized = file_format.lower()
    if normalized not in {"html", "markdown"}:
        raise ValueError("`--format` must be either `html` or `markdown`")
    if normalized == "html":
        if hasattr(filing, "save"):
            filing.save(target)
            return
        html_text = getattr(filing, "html", None)
        if callable(html_text):
            target.write_text(str(html_text()), encoding="utf-8")
            return
        raise ValueError("the filing object does not support HTML export")

    markdown_method = getattr(filing, "markdown", None)
    if callable(markdown_method):
        try:
            target.write_text(str(markdown_method()), encoding="utf-8")
            return
        except Exception:
            pass
    text_method = getattr(filing, "text", None)
    if callable(text_method):
        target.write_text(str(text_method()), encoding="utf-8")
        return
    raise ValueError("the filing object does not support markdown export")


def _bulk_download_one(
    *,
    ticker: str,
    base_output: Path,
    annual: int,
    quarters: int,
    earnings: int,
    include_financials: bool,
) -> list[str]:
    company = Company(ticker)
    company_root = base_output / ticker.upper()
    company_root.mkdir(parents=True, exist_ok=True)

    downloaded = {"10-K": 0, "10-Q": 0, "earnings": 0}
    skipped = 0

    for form, count, folder_name in [("10-K", annual, "10-K"), ("10-Q", quarters, "10-Q")]:
        target_dir = company_root / folder_name
        target_dir.mkdir(parents=True, exist_ok=True)
        for filing in _list_filings(company, form=form, limit=count):
            target = target_dir / f"{_filing_date(filing)}.md"
            if target.exists():
                skipped += 1
                continue
            _save_filing(filing, target, file_format="markdown")
            downloaded[form] += 1

    earnings_dir = company_root / "earnings"
    earnings_dir.mkdir(parents=True, exist_ok=True)
    for filing in _list_filings(company, form="8-K", limit=earnings):
        target = earnings_dir / f"{_filing_date(filing)}.md"
        if target.exists():
            skipped += 1
            continue
        try:
            _save_filing(filing, target, file_format="markdown")
            downloaded["earnings"] += 1
        except Exception:
            continue

    if include_financials:
        financials_dir = company_root / "financials"
        financials_dir.mkdir(parents=True, exist_ok=True)
        for statement_type in ["income", "balance", "cash"]:
            target = financials_dir / f"{statement_type}.md"
            if target.exists():
                skipped += 1
                continue
            frame = _fetch_financials_frame(ticker, periods=5, statement_type=statement_type).reset_index()
            target.write_text(
                f"# {ticker.upper()} {statement_type.title()} Financials\n\n{dataframe_to_markdown(frame, max_rows=40)}",
                encoding="utf-8",
            )

    return [
        f"{ticker.upper()} bulk download to {relative_display_path(company_root)}",
        f"  10-K: {downloaded['10-K']} downloaded",
        f"  10-Q: {downloaded['10-Q']} downloaded",
        f"  Earnings: {downloaded['earnings']} downloaded",
        f"  Financials: {'included' if include_financials else 'skipped'}",
        f"  Skipped: {skipped}",
        "  Errors: 0",
    ]


def _list_filings(company: Company, *, form: str, limit: int) -> list[Any]:
    if limit <= 0:
        return []
    filings = company.get_filings(form=form).latest(limit)
    try:
        return list(filings)
    except TypeError:
        return [filings]


def _filing_date(filing: Any) -> str:
    return str(getattr(filing, "filing_date", getattr(filing, "date", "latest")))


def _as_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    return value.lower() not in {"0", "false", "no"}


def _dispatch_help(subcommand: str, alternatives: list[str]) -> CommandResult:
    help_texts: dict[str, str] = {
        "10k": "Usage: sec 10k <ticker> [--items 1,1A,7]",
        "13f": "Usage: sec 13f <cik>",
        "financials": "Usage: sec financials <ticker> [--periods 5] [--type income|balance|cash]",
        "download": "Usage: sec download <ticker> [--form 10-K] [--format html|markdown] [--output PATH]",
        "bulk-download": "Usage: sec bulk-download <ticker> [<ticker2> ...] [--output DIR] [--annual 5] [--quarters 4] [--earnings 4] [--financials true|false]",
    }
    return CommandResult.from_text(
        "",
        stderr=_usage_error(
            f"missing required arguments for `sec {subcommand}`",
            help_texts[subcommand],
            alternatives,
            SEC_HELP,
        ),
        exit_code=1,
    )


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
