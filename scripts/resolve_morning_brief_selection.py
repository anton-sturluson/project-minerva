"""Resolve selected batch indices to article keys for the morning brief."""

import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
manifest = (
    json.loads((root / "results/manifest.json").read_text())
    if any(root.glob("batch-*")) else {"entries": []}
)
keys: set[str] = set()
for entry in manifest["entries"]:
    if entry["status"] != "ok":
        raise ValueError("selection extraction failed")
    rows = [json.loads(line) for line in Path(entry["source"]).read_text().splitlines()]
    if any(
        type(row["index"]) is not int or row["index"] != i
        for i, row in enumerate(rows, 1)
    ):
        raise ValueError("invalid batch indices")
    seen: set[int] = set()
    selections = Path(entry["output"]).read_text().splitlines()
    if not selections:
        raise ValueError("empty selection result")
    for line in selections:
        index = json.loads(line)["index"]
        if index is None:
            continue
        if type(index) is not int or not 1 <= index <= len(rows) or index in seen:
            raise ValueError("invalid or duplicate selection index")
        seen.add(index)
        keys.add(rows[index - 1]["article_key"])
for line in (root / "auto-advanced-keys.jsonl").read_text().splitlines():
    key = json.loads(line)["article_key"]
    if key is not None:
        keys.add(key)
(root / "selected-keys.jsonl").write_text(
    "".join(json.dumps({"article_key": key}) + "\n" for key in sorted(keys))
)
