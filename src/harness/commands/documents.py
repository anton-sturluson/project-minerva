"""Explicit source collection; publisher discovery remains agent-guided."""
from pathlib import Path
import json
import typer
from minerva.documents import create_pair, pdf2md

app = typer.Typer(help="Collect complete PDF/Markdown document pairs. No scraping or model calls.")


def _run(call):
    try:
        result = call()
    except Exception as exc:
        typer.echo(f"Document error: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(json.dumps(result, indent=2))


@app.command("pdf2md")
def pdf2md_command(
    source: Path = typer.Argument(..., help="Intact local PDF; never modified."),
    output: Path | None = typer.Option(None, "--output", "-o", help="New Markdown file; no overwrite."),
    source_url: str | None = typer.Option(None, "--source-url", help="Publisher URL for provenance."),
):
    """Convert ALL pages to one Markdown file, with page anchors and warnings."""
    _run(lambda: pdf2md(source, output or source.with_suffix(".md"), source_url))


@app.command("pair")
def pair_command(
    source: str = typer.Argument(..., help="Explicit PDF or complete Markdown path/URL."),
    output: Path = typer.Option(..., "--output", "-o", help="NEW output stem, without extension."),
    source_format: str = typer.Option(..., "--from", help="pdf (preserve original) or markdown (generated PDF)."),
    source_url: str | None = typer.Option(None, "--source-url", help="Original publisher URL for a local source."),
):
    """Create STEM.pdf + STEM.md + STEM.source.json. Existing partial pairs fail safely."""
    def collect():
        if source_format not in {"pdf", "markdown"}:
            raise ValueError("--from must be pdf or markdown")
        return create_pair(source=source, stem=output, source_format=source_format, source_url=source_url)
    _run(collect)


def pdf2md_main():
    typer.run(pdf2md_command)


if __name__ == "__main__":
    app()
