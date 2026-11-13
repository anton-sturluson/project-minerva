"""Render a validated, self-contained debt-issuance pilot snapshot as HTML."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import cast

from collect import validate_snapshot

type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]


def render(snapshot_path: Path, output_path: Path | None = None) -> Path:
    """Validate a local snapshot and embed escaped JSON in the report template."""
    snapshot: dict[str, JsonValue] = cast(
        dict[str, JsonValue], json.loads(snapshot_path.read_text(encoding="utf-8"))
    )
    validate_snapshot(snapshot)
    payload: str = json.dumps(snapshot, ensure_ascii=False, allow_nan=False)
    payload = (
        payload.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    template: str = Path(__file__).with_name("template.html").read_text(encoding="utf-8")
    if template.count("__SNAPSHOT_JSON__") != 1:
        raise ValueError("The template must contain one snapshot placeholder")
    destination: Path = output_path or snapshot_path.with_name("index.html")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(template.replace("__SNAPSHOT_JSON__", payload), encoding="utf-8")
    return destination


def main() -> None:
    """Render the supplied validated snapshot beside its source data by default."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--output", type=Path)
    arguments: argparse.Namespace = parser.parse_args()
    destination: Path = render(arguments.snapshot, arguments.output)
    print(destination)


if __name__ == "__main__":
    main()
