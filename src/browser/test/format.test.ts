import assert from "node:assert/strict";
import { test } from "node:test";
import { formatError, formatMetadata, formatSuccess } from "../src/lib/format.js";

test("metadata is stable and sanitizes elapsed time", () => {
  assert.equal(formatMetadata(true, "https://example.com", 1.6), "[ok | url: https://example.com | 2ms]");
  assert.equal(formatMetadata(false, "", -10), "[error | url: about:blank | 0ms]");
});

test("close-idle formatting distinguishes eligible, closed, skipped, and failed", () => {
  const output = formatSuccess(
    "close-idle",
    {
      dryRun: false,
      hours: 6,
      eligibleCount: 2,
      closedCount: 1,
      skippedCount: 3,
      failedCount: 1,
      eligible: [],
      closed: [{ id: 1, idleHours: 9.5, title: "Old tab", url: "https://old.example" }],
      skipped: [
        { id: 2, reason: "pinned" },
        { id: 3, reason: "active" },
        { id: 4, reason: "active" },
      ],
      failed: [{ id: 5, title: "Failed tab", stage: "close", error: "denied" }],
    },
    "about:blank",
    12,
  );

  assert.match(output, /^Eligible: 2 tab\(s\)/);
  assert.match(output, /Closed: 1 tab\(s\)\./);
  assert.match(output, /Skipped: 3 tab\(s\)\./);
  assert.match(output, /Failed: 1 tab\(s\)\./);
  assert.match(output, /Closed tabs:\n- 9\.5h — Old tab — https:\/\/old\.example/);
  assert.match(output, /Skip reasons: pinned=1, active=2/);
  assert.match(output, /Failure \(close\): Failed tab — denied/);
  assert.match(output, /\[ok \| url: about:blank \| 12ms\]$/);
});

test("close-idle dry-run formatting explicitly says nothing was closed", () => {
  const output = formatSuccess(
    "close-idle",
    {
      dryRun: true,
      hours: 12,
      eligibleCount: 1,
      closedCount: 0,
      skippedCount: 0,
      failedCount: 0,
      eligible: [{ idleHours: 14, title: "Candidate", url: "https://candidate.example" }],
      closed: [],
      skipped: [],
      failed: [],
    },
    "https://current.example",
    2,
  );
  assert.match(output, /Dry run: no tabs were closed\./);
  assert.match(output, /Eligible tabs:/);
  assert.doesNotMatch(output, /Closed tabs:/);
});

test("tabs and errors render concise human-readable output", () => {
  const tabs = formatSuccess(
    "tabs",
    [{ alias: "t0", url: "https://example.com", title: "Example", active: true }],
    "https://example.com",
    1,
  );
  assert.match(tabs, /^\* t0/);
  assert.match(tabs, /"Example"/);

  const error = formatError("bad input", "unavailable", 3);
  assert.equal(error, "[error] bad input\n[error | url: unavailable | 3ms]");
});

test("long output is truncated to the configured line limit", () => {
  const body = Array.from({ length: 205 }, (_, index) => `line ${index}`).join("\n");
  const output = formatSuccess("extract", body, "about:blank", 1);
  assert.match(output, /\[truncated: showing 200\/205 lines/);
  assert.doesNotMatch(output, /line 204/);
});
