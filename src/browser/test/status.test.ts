import assert from "node:assert/strict";
import { test } from "node:test";
import { runCommand, type CommandBridge } from "../src/server.js";
import type { BridgeAction } from "../src/lib/types.js";

class StatusBridge implements CommandBridge {
  getStatus() {
    return { connected: true, lastSeenAt: null };
  }

  async call(action: BridgeAction, params: Record<string, unknown>): Promise<unknown> {
    assert.equal(action, "status");
    if (params.tabId === "missing") throw new Error('Unknown managed tab alias "missing".');
    if (params.tabId === "stale") throw new Error("Managed tab is no longer available.");
    throw new Error("extension temporarily unavailable");
  }
}

test("status --tab propagates invalid and stale managed-tab errors", async () => {
  const bridge = new StatusBridge();
  await assert.rejects(
    runCommand({ command: "status", args: [], options: { tab: "missing" } }, bridge),
    /Unknown managed tab alias/,
  );
  await assert.rejects(
    runCommand({ command: "status", args: [], options: { tab: "stale" } }, bridge),
    /no longer available/,
  );
});

test("plain status remains diagnostic when the extension is unavailable", async () => {
  const result = await runCommand({ command: "status", args: [], options: {} }, new StatusBridge());
  assert.equal(typeof result, "object");
  assert.match((result as { message: string }).message, /temporarily unavailable/);
});
