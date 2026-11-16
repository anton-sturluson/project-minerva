"""Exercise the morning brief selection resolver."""

import json
from pathlib import Path
import shlex

import pytest
from typer.testing import CliRunner, Result

from harness.cli import app, execute_chain
from harness.config import HarnessSettings


@pytest.fixture(autouse=True)
def _workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = HarnessSettings(workspace_root=tmp_path)
    monkeypatch.setattr("harness.commands.brief.get_settings", lambda: settings)
    monkeypatch.setattr("harness.cli.get_settings", lambda: settings)


def _run_mapping(
    tmp_path: Path, results: list[list[dict]], *, bad_batch: bool = False
) -> Result:
    """Run the resolver with synthetic extractor results."""
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
    return CliRunner().invoke(
        app, ["brief", "resolve-selection", "--selection-dir", str(tmp_path)]
    )


def test_indices_resolve_within_each_batch_and_union_premium(tmp_path: Path) -> None:
    result = _run_mapping(
        tmp_path, [[{"index": 1}, {"index": 3}], [{"index": 1}], [{"index": None}]]
    )
    assert result.exit_code == 0, result.stdout
    keys = [
        json.loads(line)["article_key"]
        for line in (tmp_path / "selected-keys.jsonl").read_text().splitlines()
    ]
    assert keys == ["key-0-1", "key-0-3", "key-1-1", "premium"]


def test_misnumbered_batch_does_not_write_partial_union(tmp_path: Path) -> None:
    result = _run_mapping(tmp_path, [[{"index": 1}], [{"index": 1}]], bad_batch=True)
    assert result.exit_code != 0
    assert not (tmp_path / "selected-keys.jsonl").exists()


def test_no_batches_still_advances_premium(tmp_path: Path) -> None:
    result = _run_mapping(tmp_path, [])
    assert result.exit_code == 0, result.stdout
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
    assert result.exit_code != 0
    assert not (tmp_path / "selected-keys.jsonl").exists()


def test_run_dispatch_resolves_and_reports_failure(tmp_path: Path) -> None:
    result = _run_mapping(tmp_path, [[{"index": 1}]])
    assert result.exit_code == 0
    (tmp_path / "selected-keys.jsonl").unlink()
    command = f"brief resolve-selection --selection-dir {shlex.quote(str(tmp_path))}"
    chained = CliRunner().invoke(app, ["run", command])
    assert "[exit:0" in chained.stdout
    assert json.loads((tmp_path / "selected-keys.jsonl").read_text().splitlines()[0]) == {
        "article_key": "key-0-1"
    }
    (tmp_path / "batch-0.md").write_text('{"index":true}\n')
    failed = CliRunner().invoke(app, ["run", command])
    assert "[exit:1" in failed.stdout
    assert execute_chain(command, HarnessSettings(workspace_root=tmp_path)).exit_code == 1


def test_resolve_selection_help_and_required_directory() -> None:
    runner = CliRunner()
    assert "resolve-selection" in runner.invoke(app, ["brief", "--help"]).stdout
    assert "--selection-dir" in runner.invoke(app, ["brief", "resolve-selection", "--help"]).stdout
    assert runner.invoke(app, ["brief", "resolve-selection"]).exit_code != 0
    failed = runner.invoke(app, ["run", "brief resolve-selection"])
    assert "[exit:1" in failed.stdout


def test_file_and_json_errors_exit_nonzero(tmp_path: Path) -> None:
    runner = CliRunner()
    args = ["brief", "resolve-selection", "--selection-dir", str(tmp_path)]
    assert runner.invoke(app, args).exit_code != 0
    (tmp_path / "batch-0.jsonl").write_text("{}\n")
    (tmp_path / "results").mkdir()
    (tmp_path / "results/manifest.json").write_text("not json")
    assert runner.invoke(app, args).exit_code != 0
    assert not (tmp_path / "selected-keys.jsonl").exists()
