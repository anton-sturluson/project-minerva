"""Focused coverage for the morning-brief browser coordinator lifecycle."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
HELPER_PATH = REPO_ROOT / "scripts" / "morning_brief_helper.py"
PIPELINE_PATH = REPO_ROOT / "scripts" / "run_morning_brief.sh"
SPEC = importlib.util.spec_from_file_location("morning_brief_helper_browser", HELPER_PATH)
assert SPEC is not None and SPEC.loader is not None
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)


def _write_executable(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)
    return path


def _fake_browser(tmp_path: Path) -> tuple[Path, Path, Path]:
    state = tmp_path / "browser-state.json"
    state.write_text(json.dumps({"aliases": ["t0"], "next": 1}), encoding="utf-8")
    log = tmp_path / "browser.log"
    command = _write_executable(
        tmp_path / "fake-browser.py",
        r'''#!/usr/bin/env python3
import fcntl
import json
import os
import sys
import time
from pathlib import Path

state_path = Path(os.environ["FAKE_BROWSER_STATE"])
log_path = Path(os.environ["FAKE_BROWSER_LOG"])
lock_path = state_path.with_suffix(".lock")
args = sys.argv[1:]
with lock_path.open("a+") as lock:
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
    state = json.loads(state_path.read_text())
    with log_path.open("a") as log:
        log.write(" ".join(args) + "\n")
    if args[0] == "tabs":
        for index, alias in enumerate(state["aliases"]):
            marker = "*" if index == len(state["aliases"]) - 1 else " "
            print(f'{marker} {alias:<3} https://example.test/{alias} "{alias}"')
    elif args[0] == "open" and "--new" in args and "--window" in args:
        count = 2 if os.environ.get("FAKE_BROWSER_MULTI_OPEN") == "1" else 1
        for _ in range(count):
            alias = f't{state["next"]}'
            state["next"] += 1
            state["aliases"].append(alias)
        state_path.write_text(json.dumps(state))
        time.sleep(float(os.environ.get("FAKE_BROWSER_OPEN_DELAY", "0")))
        print("opened")
    elif args[0] == "close":
        alias = args[1]
        if alias not in state["aliases"]:
            raise SystemExit(4)
        state["aliases"].remove(alias)
        state_path.write_text(json.dumps(state))
        print(f"closed {alias}")
    else:
        if args[-2:] != ["--tab", args[-1]] or args[-1] not in state["aliases"]:
            raise SystemExit(5)
        print("ok")
''',
    )
    return command, state, log


def _browser_env(monkeypatch: pytest.MonkeyPatch, command: Path, state: Path, log: Path) -> None:
    monkeypatch.setenv("MINERVA_BROWSER_COMMAND", str(command))
    monkeypatch.setenv("FAKE_BROWSER_STATE", str(state))
    monkeypatch.setenv("FAKE_BROWSER_LOG", str(log))


def _manifest(tmp_path: Path, name: str = "lease-run.json") -> Path:
    path = tmp_path / name
    helper.initialize_lease_manifest(path, os.getpid())
    return path


def _aliases(state: Path) -> list[str]:
    return json.loads(state.read_text(encoding="utf-8"))["aliases"]


def _coordinator_envelope(completed: int) -> str:
    report = json.dumps({"status": "ok", "completed": completed}, separators=(",", ":"))
    return json.dumps(
        {
            "status": "ok",
            "result": {
                "payloads": [{"text": report}],
                "meta": {
                    "aborted": False,
                    "livenessState": "working",
                    "stopReason": "end_turn",
                },
            },
        }
    )


def _yielded_envelope(**meta_overrides: object) -> str:
    meta = {
        "aborted": False,
        "livenessState": "paused",
        "stopReason": "end_turn",
        "yielded": True,
    }
    meta.update(meta_overrides)
    return json.dumps(
        {"status": "ok", "result": {"payloads": [], "meta": meta}}
    )


def _coordinator_jobs(
    tmp_path: Path, source_ids: tuple[str, ...] = ("wsj",)
) -> tuple[Path, Path]:
    jobs = tmp_path / "jobs.json"
    results = tmp_path / "results"
    helper.initialize_coordinator_jobs(jobs, len(source_ids))
    for source_id in source_ids:
        helper.append_coordinator_job(
            jobs,
            {
                "access": "browser",
                "log_file": str(results / source_id / "collector.log"),
                "max_attempts": 2,
                "prompt_file": str(tmp_path / f"{source_id}.md"),
                "source_id": source_id,
                "source_name": source_id.upper(),
                "source_root": str(tmp_path / source_id),
                "task_name": source_id,
                "timeout": 30,
                "url": f"https://example.test/{source_id}",
            },
        )
    return jobs, results


def _record_successes(jobs: Path, results: Path, *source_ids: str) -> None:
    for source_id in source_ids:
        helper.record_coordinator_result(
            jobs, results, source_id, 1, "ok", ""
        )


def test_allocation_is_serialized_unique_and_cleanup_preserves_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    command, state, log = _fake_browser(tmp_path)
    _browser_env(monkeypatch, command, state, log)
    manifest = _manifest(tmp_path)
    monkeypatch.setenv("FAKE_BROWSER_OPEN_DELAY", "0.05")

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                helper.allocate_browser_lease,
                manifest,
                source_id,
                f"https://example.test/{source_id}",
            )
            for source_id in ("wsj", "economist")
        ]
    allocated = {future.result() for future in futures}

    assert allocated == {"t1", "t2"}
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert {lease["alias"] for lease in payload["leases"]} == allocated

    helper.cleanup_browser_leases(manifest, remove=True)

    assert _aliases(state) == ["t0"]
    assert not manifest.exists()
    close_lines = [line for line in log.read_text().splitlines() if line.startswith("close ")]
    assert set(close_lines) == {"close t1", "close t2"}
    assert "close t0" not in close_lines


def test_allocator_requires_exactly_one_new_alias_and_never_guesses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    command, state, log = _fake_browser(tmp_path)
    _browser_env(monkeypatch, command, state, log)
    monkeypatch.setenv("FAKE_BROWSER_MULTI_OPEN", "1")
    manifest = _manifest(tmp_path)

    with pytest.raises(ValueError, match="exactly one new alias"):
        helper.allocate_browser_lease(
            manifest, "wsj", "https://example.test/wsj"
        )

    assert json.loads(manifest.read_text())["leases"] == []
    assert not any(line.startswith("close ") for line in log.read_text().splitlines())


def test_stale_manifest_recovery_closes_only_recorded_aliases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    command, state, log = _fake_browser(tmp_path)
    _browser_env(monkeypatch, command, state, log)
    manifest = tmp_path / "lease-stale.json"
    helper.initialize_lease_manifest(manifest, 2**30)
    helper.allocate_browser_lease(manifest, "wsj", "https://example.test/wsj")

    recovered = helper.recover_stale_lease_manifests(tmp_path)

    assert recovered == [manifest]
    assert _aliases(state) == ["t0"]
    assert not manifest.exists()
    assert "close t0" not in log.read_text().splitlines()


def test_crawler_prompt_and_guard_target_only_the_assigned_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    command, state, log = _fake_browser(tmp_path)
    _browser_env(monkeypatch, command, state, log)
    manifest = _manifest(tmp_path)
    alias = helper.allocate_browser_lease(
        manifest, "wsj", "https://example.test/wsj"
    )
    template = (REPO_ROOT / "scripts/prompts/collect_news.md").read_text()

    prompt = helper.render_leased_browser_prompt(template, manifest, "wsj", alias)

    assert f"assigned browser alias is exactly `{alias}`" in prompt
    assert "leased-browser" in prompt
    assert "browser tabs" not in prompt
    assert "browser open" not in prompt
    assert "browser close" not in prompt
    assert "--new" not in prompt
    assert "--window" not in prompt
    assert "{{BROWSER_ALIAS}}" not in prompt
    assert "{{LEASED_BROWSER_COMMAND}}" not in prompt

    assert helper.run_leased_browser_command(
        manifest, "wsj", alias, ["snapshot", "--depth", "3"]
    ) == 0
    assert log.read_text().splitlines()[-1] == f"snapshot --depth 3 --tab {alias}"
    with pytest.raises(ValueError, match="not allowed"):
        helper.run_leased_browser_command(manifest, "wsj", alias, ["tabs"])
    with pytest.raises(ValueError, match="forbidden option"):
        helper.run_leased_browser_command(
            manifest, "wsj", alias, ["open", "https://example.test", "--new"]
        )


@pytest.mark.parametrize(
    ("script", "timeout", "expected"),
    [
        ("print(ENVELOPE)", 2, "ok"),
        ("raise SystemExit(7)", 2, "agent_error"),
        ("print('{}')", 2, "status_error"),
        ("import time; time.sleep(2)", 1, "timeout"),
    ],
)
def test_final_cleanup_on_success_failure_logical_failure_and_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    script: str,
    timeout: int,
    expected: str,
) -> None:
    command, state, log = _fake_browser(tmp_path)
    _browser_env(monkeypatch, command, state, log)
    manifest = _manifest(tmp_path)
    helper.allocate_browser_lease(manifest, "wsj", "https://example.test/wsj")
    jobs, results = _coordinator_jobs(tmp_path)
    if expected == "ok":
        _record_successes(jobs, results, "wsj")
    child = tmp_path / "parent.py"
    child.write_text(
        f"ENVELOPE = {repr(_coordinator_envelope(1))}\n{script}\n",
        encoding="utf-8",
    )

    outcome = helper.run_coordinator_process(
        [sys.executable, str(child)],
        timeout=timeout,
        lease_manifest=manifest,
        jobs_path=jobs,
        result_dir=results,
    )

    assert outcome == expected
    assert _aliases(state) == ["t0"]
    assert not manifest.exists()


def test_yielded_cli_waits_for_all_durable_statuses_before_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    command, state, log = _fake_browser(tmp_path)
    _browser_env(monkeypatch, command, state, log)
    manifest = _manifest(tmp_path)
    helper.allocate_browser_lease(manifest, "wsj", "https://example.test/wsj")
    jobs, results = _coordinator_jobs(tmp_path, ("wsj", "economist"))
    observed = tmp_path / "observed-aliases.json"
    writer = _write_executable(
        tmp_path / "delayed-writer.py",
        f'''#!/usr/bin/env python3
import json
import subprocess
import sys
import time
from pathlib import Path

time.sleep(0.25)
Path({str(observed)!r}).write_text(Path({str(state)!r}).read_text())
for source_id in ("wsj", "economist"):
    subprocess.run([
        sys.executable, {str(HELPER_PATH)!r}, "coordinator-record",
        {str(jobs)!r}, {str(results)!r}, source_id, "1", "ok", "",
    ], check=True)
''',
    )
    parent = _write_executable(
        tmp_path / "yield-parent.py",
        f'''#!/usr/bin/env python3
import subprocess
import sys
subprocess.Popen(
    [sys.executable, {str(writer)!r}],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
print({_yielded_envelope()!r})
''',
    )

    started = time.monotonic()
    outcome = helper.run_coordinator_process(
        [sys.executable, str(parent)],
        timeout=3,
        lease_manifest=manifest,
        jobs_path=jobs,
        result_dir=results,
    )

    assert outcome == "ok"
    assert time.monotonic() - started >= 0.2
    assert json.loads(observed.read_text())["aliases"] == ["t0", "t1"]
    assert helper.coordinator_results_outcome(jobs, results) == "ok"
    assert _aliases(state) == ["t0"]
    assert not manifest.exists()


def test_yielded_missing_status_times_out_finalizes_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    command, state, log = _fake_browser(tmp_path)
    _browser_env(monkeypatch, command, state, log)
    manifest = _manifest(tmp_path)
    helper.allocate_browser_lease(manifest, "wsj", "https://example.test/wsj")
    jobs, results = _coordinator_jobs(tmp_path)
    parent = _write_executable(
        tmp_path / "yield-parent.py",
        f"#!/usr/bin/env python3\nprint({_yielded_envelope()!r})\n",
    )

    outcome = helper.run_coordinator_process(
        [sys.executable, str(parent)],
        timeout=1,
        lease_manifest=manifest,
        jobs_path=jobs,
        result_dir=results,
    )

    status = json.loads((results / "wsj" / "status.json").read_text())
    assert outcome == "timeout"
    assert status["status"] == "failed"
    assert status["error"] == "coordinator_failed"
    assert _aliases(state) == ["t0"]
    assert not manifest.exists()


def test_invalid_durable_status_is_replaced_with_failed_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    command, state, log = _fake_browser(tmp_path)
    _browser_env(monkeypatch, command, state, log)
    manifest = _manifest(tmp_path)
    helper.allocate_browser_lease(manifest, "wsj", "https://example.test/wsj")
    jobs, results = _coordinator_jobs(tmp_path)
    status_path = results / "wsj" / "status.json"
    status_path.parent.mkdir(parents=True)
    status_path.write_text('{"status":"ok"}\n', encoding="utf-8")
    parent = _write_executable(
        tmp_path / "yield-parent.py",
        f"#!/usr/bin/env python3\nprint({_yielded_envelope()!r})\n",
    )

    outcome = helper.run_coordinator_process(
        [sys.executable, str(parent)],
        timeout=2,
        lease_manifest=manifest,
        jobs_path=jobs,
        result_dir=results,
    )

    status = json.loads(status_path.read_text())
    assert outcome == "invalid_report"
    assert status["status"] == "failed"
    assert status["error"] == "coordinator_failed"
    assert _aliases(state) == ["t0"]
    assert not manifest.exists()


def test_malformed_yield_is_rejected_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    command, state, log = _fake_browser(tmp_path)
    _browser_env(monkeypatch, command, state, log)
    manifest = _manifest(tmp_path)
    helper.allocate_browser_lease(manifest, "wsj", "https://example.test/wsj")
    jobs, results = _coordinator_jobs(tmp_path)
    parent = _write_executable(
        tmp_path / "malformed-yield.py",
        f"#!/usr/bin/env python3\nprint({_yielded_envelope(livenessState='working')!r})\n",
    )

    outcome = helper.run_coordinator_process(
        [sys.executable, str(parent)],
        timeout=2,
        lease_manifest=manifest,
        jobs_path=jobs,
        result_dir=results,
    )

    assert outcome == "invalid_result"
    assert _aliases(state) == ["t0"]
    assert not manifest.exists()


def test_retry_closes_previous_lease_before_allocating_fresh_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    command, state, log = _fake_browser(tmp_path)
    _browser_env(monkeypatch, command, state, log)
    manifest = _manifest(tmp_path)

    first = helper.allocate_browser_lease(
        manifest, "economist", "https://example.test/economist"
    )
    helper.close_browser_lease(manifest, "economist", first)
    second = helper.allocate_browser_lease(
        manifest, "economist", "https://example.test/economist"
    )

    assert (first, second) == ("t1", "t2")
    lines = log.read_text().splitlines()
    first_close = lines.index("close t1")
    second_open = [i for i, line in enumerate(lines) if line.startswith("open ")][1]
    assert first_close < second_open

    helper.cleanup_browser_leases(manifest, remove=True)
    assert _aliases(state) == ["t0"]


def test_run_coordinator_cli_cleans_lease_when_sent_sigterm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    command, state, log = _fake_browser(tmp_path)
    _browser_env(monkeypatch, command, state, log)
    manifest = _manifest(tmp_path)
    helper.allocate_browser_lease(manifest, "wsj", "https://example.test/wsj")
    jobs, results = _coordinator_jobs(tmp_path)
    sleeper = _write_executable(
        tmp_path / "yield-parent.py",
        f"#!/usr/bin/env python3\nprint({_yielded_envelope()!r})\n",
    )
    env = os.environ.copy()
    process = subprocess.Popen(
        [
            sys.executable,
            str(HELPER_PATH),
            "run-coordinator",
            str(manifest),
            str(jobs),
            str(results),
            "60",
            "--",
            str(sleeper),
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    time.sleep(0.2)
    assert process.poll() is None
    assert _aliases(state) == ["t0", "t1"]
    process.terminate()
    process.communicate(timeout=10)

    assert process.returncode == 130
    status = json.loads((results / "wsj" / "status.json").read_text())
    assert status["status"] == "failed"
    assert status["error"] == "coordinator_failed"
    assert _aliases(state) == ["t0"]
    assert not manifest.exists()


def test_pipeline_has_one_fixed_main_parent_and_versioned_coordinator_prompt() -> None:
    script = PIPELINE_PATH.read_text(encoding="utf-8")
    coordinator = (
        REPO_ROOT / "scripts/prompts/morning_brief_coordinator.md"
    ).read_text(encoding="utf-8")
    for prompt_name in ("collect_news.md", "collect_ir_batch.md"):
        crawler = (REPO_ROOT / "scripts/prompts" / prompt_name).read_text()
        assert crawler.count("{{BROWSER_ALIAS}}") == 1
        assert "{{LEASED_BROWSER_COMMAND}}" in crawler
        assert "browser tabs" not in crawler
        assert "browser open" not in crawler
        assert "browser close" not in crawler
        assert "--new" not in crawler
        assert "--window" not in crawler

    assert script.count("openclaw agent") == 1
    assert "openclaw agent --json --agent main" in script
    assert "trap 'terminate_pipeline TERM 143' TERM" in script
    assert "trap 'terminate_pipeline INT 130' INT" in script
    assert "MINERVA_NEWS_COLLECTOR_AGENT" not in script
    assert "sessions_spawn" in coordinator
    assert "sessions_yield" in coordinator
    assert "no `agentId` argument" in coordinator
    assert "lease-close" in coordinator
    assert coordinator.index("lease-close") < coordinator.index("fresh retry lease")
