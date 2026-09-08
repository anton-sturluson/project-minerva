import assert from "node:assert/strict";
import { test } from "node:test";
import { executeCommand, runCommand, type CommandBridge } from "../src/server.js";
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

test("response metadata reads location from the explicitly targeted tab", async () => {
  const calls: Array<{ action: BridgeAction; params: Record<string, unknown> }> = [];
  const bridge: CommandBridge = {
    getStatus: () => ({ connected: true, lastSeenAt: null }),
    async call(action, params) {
      calls.push({ action, params });
      if (action === "extract") return "Target tab content";
      if (action === "status") {
        return { url: `https://example.test/${String(params.tabId)}`, title: "Target tab" };
      }
      throw new Error(`unexpected action: ${action}`);
    },
  };

  const response = await executeCommand(
    { command: "extract", args: [], options: { tab: "t7" } },
    undefined,
    bridge,
  );

  assert.equal(response.ok, true);
  assert.equal(response.url, "https://example.test/t7");
  assert.deepEqual(calls, [
    { action: "extract", params: { selector: null, scope: null, json: false, limit: 20, tabId: "t7" } },
    { action: "status", params: { tabId: "t7" } },
  ]);
});

test("error metadata also reads location from the explicitly targeted tab", async () => {
  const calls: Array<{ action: BridgeAction; params: Record<string, unknown> }> = [];
  const bridge: CommandBridge = {
    getStatus: () => ({ connected: true, lastSeenAt: null }),
    async call(action, params) {
      calls.push({ action, params });
      if (action === "extract") throw new Error("extract failed");
      if (action === "status") return { url: "https://example.test/t8", title: "Target tab" };
      throw new Error(`unexpected action: ${action}`);
    },
  };

  const response = await executeCommand(
    { command: "extract", args: [], options: { tab: "t8" } },
    undefined,
    bridge,
  );

  assert.equal(response.ok, false);
  assert.equal(response.error, "extract failed");
  assert.equal(response.url, "https://example.test/t8");
  assert.deepEqual(calls.at(-1), { action: "status", params: { tabId: "t8" } });
});
