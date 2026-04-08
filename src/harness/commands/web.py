"""Web search and fetch commands."""

from __future__ import annotations

import time

import httpx
import typer
from bs4 import BeautifulSoup

from harness.commands.common import retry_call, should_retry_http_error
from harness.config import HarnessSettings, get_settings
from harness.output import CommandResult, OutputEnvelope

app = typer.Typer(
    help=(
        "Web research tools.\n\n"
        "Examples:\n"
        "  minerva web search \"vertical software market map\"\n"
        "  minerva web fetch https://example.com/article"
    ),
    no_args_is_help=True,
)


def dispatch(
    args: list[str],
    settings: HarnessSettings | None = None,
    stdin: bytes = b"",
) -> CommandResult:
    """Source-of-truth parser for `run` path web commands."""
    _ = stdin
    active_settings: HarnessSettings = settings or get_settings()
    if not args:
        return _usage_error("web", "Usage: web <search|fetch> <value>", ["web search <query>", "web fetch <url>"])

    subcommand: str = args[0]
    if subcommand == "search":
        if len(args) < 2:
            return _usage_error("web search", "Usage: web search <query>", ["web fetch <url>"])
        return search_web(" ".join(args[1:]), settings=active_settings)
    if subcommand == "fetch":
        if len(args) != 2:
            return _usage_error("web fetch", "Usage: web fetch <url>", ["web search <query>"])
        return fetch_url(args[1])
    return _usage_error("web", f"Unknown web subcommand: {subcommand}", ["web search <query>", "web fetch <url>"])


def search_web(query: str, settings: HarnessSettings | None = None) -> CommandResult:
    """Search the web with the Brave Search API."""
    start: float = time.perf_counter()
    active_settings: HarnessSettings = settings or get_settings()
    if not active_settings.brave_api_key:
        return CommandResult.from_text(
            "",
            stderr=(
                "Missing BRAVE_API_KEY.\n"
                "What to do instead: export BRAVE_API_KEY before using `web search`.\n"
                "Available alternatives: `web fetch <url>`, `cat <file>`"
            ),
            exit_code=1,
            duration_ms=_elapsed_ms(start),
        )

    headers: dict[str, str] = {
        "Accept": "application/json",
        "X-Subscription-Token": active_settings.brave_api_key,
    }
    params: dict[str, str | int] = {"q": query, "count": 5}

    try:
        response = retry_call(
            lambda: _search_request(headers=headers, params=params),
            should_retry=should_retry_http_error,
        )
    except (httpx.HTTPError, httpx.InvalidURL) as exc:
        return CommandResult.from_text(
            "",
            stderr=(
                f"Search failed: {exc}\n"
                "What to do instead: verify the query and API key, then retry.\n"
                "Available alternatives: `web fetch <url>`"
            ),
            exit_code=1,
            duration_ms=_elapsed_ms(start),
        )

    payload: dict = response.json()
    results: list[dict] = payload.get("web", {}).get("results", [])
    if not results:
        return CommandResult.from_text("No results found.", duration_ms=_elapsed_ms(start))

    lines: list[str] = []
    for item in results:
        title: str = item.get("title", "(untitled)")
        url: str = item.get("url", "")
        snippet: str = item.get("description", "").strip()
        lines.append(f"{title}\n{url}\n{snippet}".strip())

    return CommandResult.from_text("\n\n".join(lines), duration_ms=_elapsed_ms(start))


def fetch_url(url: str) -> CommandResult:
    """Fetch a URL and extract readable content."""
    start: float = time.perf_counter()
    try:
        response = retry_call(
            lambda: _fetch_request(url),
            should_retry=should_retry_http_error,
        )
    except (httpx.HTTPError, httpx.InvalidURL) as exc:
        return CommandResult.from_text(
            "",
            stderr=(
                f"Fetch failed: {exc}\n"
                "What to do instead: verify the URL and retry.\n"
                "Available alternatives: `web search <query>`"
            ),
            exit_code=1,
            duration_ms=_elapsed_ms(start),
        )

    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    title: str = soup.title.get_text(" ", strip=True) if soup.title else url
    paragraphs: list[str] = []
    for node in soup.find_all(["article", "main", "p", "h1", "h2", "h3", "li"]):
        text: str = node.get_text(" ", strip=True)
        if text:
            paragraphs.append(text)

    readable_text: str = "\n".join(paragraphs[:500]).strip()
    if not readable_text:
        readable_text = soup.get_text("\n", strip=True)

    body: str = f"{title}\n\n{readable_text}".strip()
    return CommandResult.from_text(body, duration_ms=_elapsed_ms(start))


@app.command("search")
def search_command(query: str = typer.Argument(..., help="Search query. Example: \"travel software margins\"")) -> None:
    """Search the web and return title, URL, and snippet for top results."""
    envelope = OutputEnvelope.from_result(search_web(query), workspace_root=get_settings().ensure_workspace_root())
    typer.echo(envelope.render())


@app.command("fetch")
def fetch_command(url: str = typer.Argument(..., help="URL to fetch. Example: https://example.com/article")) -> None:
    """Fetch a URL and extract readable page content."""
    envelope = OutputEnvelope.from_result(fetch_url(url), workspace_root=get_settings().ensure_workspace_root())
    typer.echo(envelope.render())


def _elapsed_ms(start: float) -> int:
    return max(0, int((time.perf_counter() - start) * 1000))


def _search_request(*, headers: dict[str, str], params: dict[str, str | int]) -> httpx.Response:
    response = httpx.get(
        "https://api.search.brave.com/res/v1/web/search",
        headers=headers,
        params=params,
        timeout=15.0,
    )
    response.raise_for_status()
    return response


def _fetch_request(url: str) -> httpx.Response:
    response = httpx.get(url, timeout=20.0, follow_redirects=True)
    response.raise_for_status()
    return response


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
