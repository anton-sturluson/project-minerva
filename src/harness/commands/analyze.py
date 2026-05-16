"""Text analysis commands."""

from __future__ import annotations

import math
import re
import time
from collections import Counter, defaultdict

import typer

from harness.commands.common import abort_with_help, elapsed_ms, error_result, parse_flag_args, read_text_input
from harness.config import HarnessSettings, get_settings
from harness.output import CommandResult, OutputEnvelope

ANALYZE_HELP = (
    "Deterministic text analysis commands.\n\n"
    "Examples:\n"
    "  minerva analyze ngrams apple-10k.md --top 20 --min-count 3\n"
    "  minerva run \"sec 10k AAPL --items 1A | analyze ngrams --top 15\"\n"
    "  minerva run \"sec 10k AAPL --items 1A | analyze topics --clusters 5\"\n"
)

TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9'-]*")
app = typer.Typer(help=ANALYZE_HELP, no_args_is_help=True)

def dispatch(
    args: list[str],
    settings: HarnessSettings,
    stdin: bytes = b"",
) -> CommandResult:
    """Source-of-truth parser for `run` path analysis commands."""
    if not args:
        return CommandResult.from_text(
            "",
            stderr=_usage_error(
                "no `analyze` subcommand was provided",
                "choose `ngrams` or `topics`",
                ["`analyze ngrams sample.txt --top 20`", "`analyze topics sample.txt --clusters 5`"],
                ANALYZE_HELP,
            ),
            exit_code=1,
        )

    subcommand: str = args[0]
    try:
        if subcommand == "ngrams":
            file_path, parsed = _split_file_and_flags(args[1:])
            return analyze_ngrams_command(
                file_path=file_path,
                stdin=stdin,
                top=int(parsed.get("top", 20)),
                min_count=int(parsed.get("min-count", 3)),
            )
        if subcommand == "topics":
            file_path, parsed = _split_file_and_flags(args[1:])
            return analyze_topics_command(
                file_path=file_path,
                stdin=stdin,
                clusters=int(parsed.get("clusters", 5)),
                min_count=int(parsed.get("min-count", 3)),
            )
    except ValueError as exc:
        return CommandResult.from_text("", stderr=str(exc), exit_code=1)

    return CommandResult.from_text(
        "",
        stderr=_usage_error(
            f"unknown `analyze` subcommand `{subcommand}`",
            "choose `ngrams` or `topics`",
            ["`analyze ngrams sample.txt --top 20`", "`analyze topics sample.txt --clusters 5`"],
            ANALYZE_HELP,
        ),
        exit_code=1,
    )

def analyze_ngrams_command(
    *,
    file_path: str | None = None,
    stdin: bytes = b"",
    top: int = 20,
    min_count: int = 3,
) -> CommandResult:
    start = time.perf_counter()
    try:
        from minerva.formatting import build_markdown_table

        text = read_text_input(file_path=file_path, stdin=stdin)
    except Exception as exc:
        return error_result(
            f"failed to read input text: {exc}",
            "pass a text file path or pipe text into the command",
            ["`minerva analyze ngrams sample.txt`", "`minerva run \"sec 10k AAPL --items 1A | analyze ngrams --top 15\"`"],
            start,
        )

    tokenized = _filtered_tokens(text)
    word_count = max(len(tokenized), 1)
    sections: list[str] = []
    for n, title in [(1, "Unigrams"), (2, "Bigrams"), (3, "Trigrams")]:
        counter = _ngram_counter(tokenized, n=n, min_count=min_count)
        rows: list[list[str]] = []
        for term, count in counter.most_common(top):
            density = (count / word_count) * 10_000
            rows.append([term, str(count), f"{density:.1f}"])
        sections.append(f"## {title}\n\n{build_markdown_table(['term', 'count', 'mentions_per_10k_words'], rows or [['(none)', '0', '0.0']], alignment=['l', 'r', 'r'])}")
    return CommandResult.from_text("\n\n".join(sections), duration_ms=elapsed_ms(start))

def analyze_topics_command(
    *,
    file_path: str | None = None,
    stdin: bytes = b"",
    clusters: int = 5,
    min_count: int = 3,
) -> CommandResult:
    start = time.perf_counter()
    try:
        text = read_text_input(file_path=file_path, stdin=stdin)
    except Exception as exc:
        return error_result(
            f"failed to read input text: {exc}",
            "pass a text file path or pipe text into the command",
            ["`minerva analyze topics sample.txt --clusters 5`", "`minerva run \"sec 10k AAPL --items 1A | analyze topics --clusters 5\"`"],
            start,
        )

    paragraphs: list[list[str]] = []
    for paragraph in [part.strip() for part in text.split("\n\n") if part.strip()]:
        tokens = _filtered_tokens(paragraph)
        if tokens:
            paragraphs.append(tokens)

    candidate_counts: Counter[str] = Counter()
    for n in (1, 2, 3):
        candidate_counts.update(_ngram_counter(_filtered_tokens(text), n=n, min_count=min_count))
    top_terms = [term for term, _ in candidate_counts.most_common(max(clusters * 8, 20))]
    if not top_terms:
        return CommandResult.from_text("No topic terms met the frequency threshold.", duration_ms=elapsed_ms(start))

    term_sets: dict[str, set[str]] = {term: set(term.split()) for term in top_terms}
    paragraph_presence: dict[str, set[int]] = defaultdict(set)
    for idx, paragraph_tokens in enumerate(paragraphs):
        paragraph_joined = " ".join(paragraph_tokens)
        for term, pieces in term_sets.items():
            if len(pieces) == 1:
                if next(iter(pieces)) in paragraph_tokens:
                    paragraph_presence[term].add(idx)
            elif term in paragraph_joined:
                paragraph_presence[term].add(idx)

    seeds: list[str] = []
    for term in top_terms:
        if not seeds:
            seeds.append(term)
            continue
        if all(_affinity(term, seed, paragraph_presence) <= 1 for seed in seeds):
            seeds.append(term)
        if len(seeds) == clusters:
            break
    while len(seeds) < min(clusters, len(top_terms)):
        seeds.append(top_terms[len(seeds)])

    grouped: dict[str, list[str]] = {seed: [seed] for seed in seeds}
    for term in top_terms:
        if term in grouped:
            continue
        best_seed = max(seeds, key=lambda seed: (_affinity(term, seed, paragraph_presence), candidate_counts[seed]))
        grouped[best_seed].append(term)

    word_count = max(len(_filtered_tokens(text)), 1)
    sections: list[str] = []
    for index, seed in enumerate(seeds, start=1):
        members = sorted(grouped[seed], key=lambda item: (-candidate_counts[item], item))[:6]
        total_count = sum(candidate_counts[item] for item in members)
        density = (total_count / word_count) * 10_000
        member_text = ", ".join(f"{item} ({candidate_counts[item]})" for item in members)
        sections.append(f'Topic {index}: "{seed}" (density: {density:.1f} per 10K words)\n  {member_text}')
    return CommandResult.from_text("\n\n".join(sections), duration_ms=elapsed_ms(start))

@app.command("ngrams", help="Extract frequent non-stopword unigrams, bigrams, and trigrams.\n\nExample:\n  minerva analyze ngrams apple-10k.md --top 20 --min-count 3")
def ngrams_cli_command(
    ctx: typer.Context,
    file_path: str | None = typer.Argument(None, help="Input text file path. Omit to read from stdin."),
    top: int = typer.Option(20, "--top", help="Number of top n-grams to show per type."),
    min_count: int = typer.Option(3, "--min-count", help="Minimum count to include."),
) -> None:
    if not file_path and not _stdin_available():
        abort_with_help(
            ctx,
            what_went_wrong="no input text was provided for `analyze ngrams`",
            what_to_do="pass a file path or pipe text into the command",
            alternatives=["`minerva analyze ngrams apple-10k.md --top 20`", "`minerva run \"sec 10k AAPL --items 1A | analyze ngrams --top 15\"`"],
        )
    _print(analyze_ngrams_command(file_path=file_path, stdin=typer.get_binary_stream("stdin").read(), top=top, min_count=min_count))

@app.command("topics", help="Discover topic clusters from document term co-occurrence.\n\nExample:\n  minerva analyze topics apple-10k.md --clusters 5 --min-count 3")
def topics_cli_command(
    ctx: typer.Context,
    file_path: str | None = typer.Argument(None, help="Input text file path. Omit to read from stdin."),
    clusters: int = typer.Option(5, "--clusters", help="Number of topic clusters."),
    min_count: int = typer.Option(3, "--min-count", help="Minimum term frequency to include."),
) -> None:
    if not file_path and not _stdin_available():
        abort_with_help(
            ctx,
            what_went_wrong="no input text was provided for `analyze topics`",
            what_to_do="pass a file path or pipe text into the command",
            alternatives=["`minerva analyze topics apple-10k.md --clusters 5`", "`minerva run \"sec 10k AAPL --items 1A | analyze topics --clusters 5\"`"],
        )
    _print(analyze_topics_command(file_path=file_path, stdin=typer.get_binary_stream("stdin").read(), clusters=clusters, min_count=min_count))

def _split_file_and_flags(args: list[str]) -> tuple[str | None, dict[str, str | bool]]:
    file_path: str | None = None
    if args and not args[0].startswith("--"):
        file_path = args[0]
        args = args[1:]
    parsed = parse_flag_args(args)
    return file_path, parsed

def _filtered_tokens(text: str) -> list[str]:
    from minerva.text_analysis import DEFAULT_FINANCIAL_STOPWORDS

    return [
        token
        for token in (match.group(0).lower() for match in TOKEN_RE.finditer(text))
        if token not in DEFAULT_FINANCIAL_STOPWORDS and len(token) > 2 and not token.isdigit()
    ]

def _ngram_counter(tokens: list[str], *, n: int, min_count: int) -> Counter[str]:
    counts: Counter[str] = Counter(" ".join(tokens[index : index + n]) for index in range(0, max(len(tokens) - n + 1, 0)))
    return Counter({term: count for term, count in counts.items() if count >= min_count})

def _affinity(term: str, seed: str, paragraph_presence: dict[str, set[int]]) -> int:
    return len(paragraph_presence.get(term, set()) & paragraph_presence.get(seed, set()))

def _stdin_available() -> bool:
    return not typer.get_text_stream("stdin").isatty()

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
