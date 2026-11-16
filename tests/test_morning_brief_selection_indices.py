"""Exercise the selection mapping in the synthesis contract."""

import json
import os
from pathlib import Path
import subprocess

import pytest


PROMPT = (
    Path(__file__).resolve().parents[1]
    / "scripts/prompts/morning_brief_synthesis.md"
)


def _run_mapping(
    tmp_path: Path, results: list[list[dict]], *, bad_batch: bool = False
) -> subprocess.CompletedProcess[str]:
    """Run the prompt's mapping command with synthetic extractor results."""
    entries = []
    for number, selections in enumerate(results):
        batch = tmp_path / f"batch-{number}.jsonl"
        output = tmp_path / f"batch-{number}.md"
        batch.write_text(
            "".join(
                json.dumps({"index": i, "article_key": f"key-{number}-{i}"}) + "\n"
                for i in range(1, 4 if number == 0 else 2)
            )
        )
        if bad_batch and number == 0:
            batch.write_text(json.dumps({"index": 2, "article_key": "wrong"}) + "\n")
        output.write_text("".join(json.dumps(row) + "\n" for row in selections))
        entries.append({"source": str(batch), "output": str(output), "status": "ok"})
    (tmp_path / "results").mkdir()
    if entries:
        (tmp_path / "results/manifest.json").write_text(json.dumps({"entries": list(reversed(entries))}))
    (tmp_path / "auto-advanced-keys.jsonl").write_text('{"article_key":"premium"}\n')
    command = PROMPT.read_text().split("```bash\nSELECTION_TMP=", 1)[1]
    command = command.split("\n```", 1)[0]
    return subprocess.run(
        "SELECTION_TMP=" + command,
        shell=True,
        env={**os.environ, "SELECTION_TMP": str(tmp_path)},
        text=True,
        capture_output=True,
        check=False,
    )


def test_indices_resolve_within_each_batch_and_union_premium(tmp_path: Path) -> None:
    result = _run_mapping(
        tmp_path, [[{"index": 1}, {"index": 3}], [{"index": 1}], [{"index": None}]]
    )
    assert result.returncode == 0, result.stderr
    keys = [
        json.loads(line)["article_key"]
        for line in (tmp_path / "selected-keys.jsonl").read_text().splitlines()
    ]
    assert keys == ["key-0-1", "key-0-3", "key-1-1", "premium"]


def test_misnumbered_batch_does_not_write_partial_union(tmp_path: Path) -> None:
    result = _run_mapping(tmp_path, [[{"index": 1}], [{"index": 1}]], bad_batch=True)
    assert result.returncode != 0
    assert not (tmp_path / "selected-keys.jsonl").exists()


def test_no_batches_still_advances_premium(tmp_path: Path) -> None:
    result = _run_mapping(tmp_path, [])
    assert result.returncode == 0, result.stderr
    assert json.loads((tmp_path / "selected-keys.jsonl").read_text()) == {
        "article_key": "premium"
    }


@pytest.mark.parametrize(
    "selections",
    [
        [{"index": 0}],
        [{"index": -1}],
        [{"index": 4}],
        [{"index": True}],
        [{"index": 1.0}],
        [{"index": "1"}],
        [{}],
        [{"index": 1}, {"index": 1}],
        [],
    ],
)
def test_invalid_selection_does_not_write_partial_union(
    tmp_path: Path, selections: list[dict]
) -> None:
    result = _run_mapping(tmp_path, [selections, [{"index": 1}]])
    assert result.returncode != 0
    assert not (tmp_path / "selected-keys.jsonl").exists()
