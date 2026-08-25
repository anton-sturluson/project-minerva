# Morning-Brief Browser Coordinator Plan

**Date:** 2026-08-25
**Status:** Implemented and live-verified

## Goal

Replace the per-collector `openclaw agent --agent main` processes with one top-level OpenClaw `main` coordinator. The coordinator delegates isolated native subagent runs, assigns one deterministically allocated Chrome lease to each browser crawler, and leaves lease lifecycle enforcement and cleanup to deterministic code.

## Design

1. `run_morning_brief.sh` continues to select sources, render isolated collector prompts, preserve direct SQLite ingestion, and aggregate the existing `status.json`/`collectors.json` contracts. It writes an ordered run-scoped job manifest instead of launching one OpenClaw process per source.
2. The shell invokes exactly one top-level `openclaw agent --agent main` process with a versioned coordinator prompt. That parent uses `sessions_spawn` (without an explicit `agentId`, so native children inherit `main`) and `sessions_yield` to dispatch crawler agents in bounded parallel waves and receive their compact reports. A live OpenClaw test verified that the initial CLI process exits successfully as soon as the parent yields: the JSON result has `payloads: []`, `meta.aborted: false`, `meta.yielded: true`, `meta.livenessState: "paused"`, and `meta.stopReason: "end_turn"`. OpenClaw later runs a continuation turn in the same parent session when children complete.
3. Before each browser child is spawned, the parent invokes the deterministic helper. Under one cross-run file lock, the helper snapshots managed aliases, opens exactly one new window, snapshots again, requires a set difference of exactly one alias, and atomically records that alias in a run manifest. It never infers an alias from command output or active-tab state.
4. The helper renders an attempt prompt containing the assigned alias and a lease-checked browser command. That command verifies the source/alias against the manifest, forbids tab enumeration, new tabs/windows, focus, and close, and appends the one assigned alias to every permitted browser operation. Browser crawler prompts also forbid raw browser commands and leave the lease open. Web-fetch prompts remain browser-free.
5. On a failed attempt, the parent must invoke the helper to close the prior recorded lease before allocation of a fresh lease. The helper rejects a new allocation while that source has an open lease.
6. A deterministic process wrapper owns the initial top-level CLI process and validates either (a) the exact healthy yielded/paused shape above or (b) a complete, non-yielded final envelope. It rejects mixed or ambiguous yield state, malformed payloads, aborts, timeouts, and agent errors. After a valid yield, the wrapper remains alive and waits on the filesystem—not on the exited CLI process, a parent reply, OpenClaw sessions, or task polling—until every manifest job has a valid final status artifact under the collector result root. One overall deadline and the SIGTERM/SIGINT handlers remain active across both the CLI turn and this durable-status wait.
7. The continuation records each collector status through `coordinator-record`, which atomically publishes the final JSON artifact without overwriting an existing result. The jobs manifest plus result root are the durable completion contract. In `finally`, the wrapper closes only still-open aliases explicitly recorded in the run manifest and replaces missing or invalid collector results with `coordinator_failed`; this applies after success, process or envelope failure, timeout, and signal. Ordinary coordinator failures remain a degraded collector outcome, while an intercepted SIGTERM/SIGINT exits the outer pipeline after cleanup. A narrowly scoped startup recovery pass handles lease manifests whose owner PID no longer exists after SIGKILL or host interruption. Existing summary/evidence gates remain unchanged.

## OpenClaw constraint

OpenClaw native subagents are the smallest literal parent/child architecture available: `sessions_spawn` is non-blocking, `sessions_yield` pauses the current parent turn, and child completion causes OpenClaw to run a continuation in the same parent session. The one-shot CLI invocation does **not** remain attached until that continuation finishes. The installed OpenClaw API also does **not** accept a per-spawn timeout; it uses one configured global subagent timeout. Therefore the existing source timeout values cannot be enforced independently inside one parent turn. The implementation retains them as job metadata and applies one deterministic coordinator deadline, sized for the bounded-parallel waves and retry path, across initial dispatch and the durable artifact wait. This is documented rather than simulated with additional top-level `openclaw agent` processes.

## Files

- Add `scripts/prompts/morning_brief_coordinator.md`.
- Extend `scripts/morning_brief_helper.py` with job/result manifests, lease allocation and guarded commands, stale recovery, coordinator process lifecycle, and coordinator-result validation.
- Update `scripts/run_morning_brief.sh` to build jobs and launch one parent.
- Update browser collector prompts to consume an assigned lease and never create or close tabs.
- Add focused helper/coordinator tests and adapt collection integration coverage to the one-parent contract.

## Verification

Run focused automated tests for:

- serialized unique allocation and exact alias-difference validation;
- browser prompt restrictions and deterministic alias targeting;
- strict acceptance of the verified yielded/paused envelope and rejection of malformed or ambiguous yield output;
- delayed status publication after the CLI exits, with leases demonstrably open during the filesystem wait and closed only after every status appears;
- cleanup and failed-artifact finalization after process/logical failure, missing-result timeout, SIGTERM during the filesystem wait, and retry;
- closing the prior retry lease before a fresh allocation;
- no remaining recorded aliases and no closure of baseline aliases;
- one top-level `main` coordinator invocation and preserved collector artifacts.

Live verification completed on 2026-08-25:

- A real `main` coordinator spawned one browser crawler against `https://example.com`. The leased tab remained open while the wrapper waited, the continuation wrote a valid `status.json`, and cleanup removed the lease with zero managed tabs remaining.
- A real Chrome lease was then allocated before a simulated nonzero parent-process exit. The wrapper produced a failed collector status and closed the leased tab, again leaving zero managed tabs.
