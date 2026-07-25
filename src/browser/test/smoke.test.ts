import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { parseCliInput } from "../src/lib/parse.js";
import { runCommand, type CommandBridge, type OracleRunner } from "../src/server.js";
import { CLOSE_IDLE_TIMEOUT_MS, type BridgeAction, type CommandName, type CommandRequest } from "../src/lib/types.js";

class FakeBridge implements CommandBridge {
  readonly calls: Array<{ action: BridgeAction; params: Record<string, unknown>; timeoutMs?: number }> = [];

  getStatus() {
    return { connected: false, lastSeenAt: null };
  }

  async call(action: BridgeAction, params: Record<string, unknown>, timeoutMs?: number): Promise<unknown> {
    this.calls.push({ action, params, timeoutMs });
    switch (action) {
      case "open":
        return { url: "https://example.test", title: "Example", preview: "ready" };
      case "tabs":
        return [];
      case "focus":
      case "close":
        return { alias: "t0", tabId: 1, url: "https://example.test", title: "Example", active: action === "focus" };
      case "close-idle":
        return {
          dryRun: true,
          hours: params.hours,
          eligibleCount: 0,
          closedCount: 0,
          skippedCount: 0,
          failedCount: 0,
          eligible: [],
          closed: [],
          skipped: [],
          failed: [],
        };
      case "click":
        return { clicked: params.target, target: params.target, title: "Example", preview: "ready" };
      case "type":
        return { typedInto: params.target, target: params.target, text: params.text };
      case "fill":
        return { filledInto: params.target, target: params.target, intended: params.text, actual: params.text, match: true };
      case "upload":
        return { uploaded: params.filepath, target: params.target, selector: "input", title: "Example", preview: "ready" };
      case "wait":
        return { condition: "delay", waitedMs: 0, url: "https://example.test", title: "Example" };
      case "snapshot":
        return { snapshot: "page \"Example\"", url: "https://example.test", title: "Example" };
      case "diff":
        return { diff: "No changes since last snapshot.", url: "https://example.test", title: "Example" };
      case "inspect":
        return { elements: [], url: "https://example.test", title: "Example" };
      case "extract":
        return "Example text";
      case "screenshot":
        return { dataUrl: "data:image/png;base64,iVBORw0KGgo=", mode: "viewport", url: "https://example.test", title: "Example" };
      case "html":
        return "<html></html>";
      case "eval":
        return "Example";
      case "dialog":
        return { open: false, url: "https://example.test", title: "Example" };
      case "status":
        return { url: "https://example.test", title: "Example", managedTabs: [] };
    }
  }
}

function requestFromArgv(argv: string[], cwd: string): CommandRequest {
  const parsed = parseCliInput(argv, cwd);
  assert.equal(parsed.localOutput, undefined, parsed.localOutput?.text);
  assert.ok(parsed.command);
  return { command: parsed.command, args: parsed.args, options: parsed.options };
}

test("every Browser CLI command runs through parsing and dispatch without live services", async () => {
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), "browser-smoke-"));
  const uploadPath = path.join(tempDir, "upload.txt");
  const screenshotPath = path.join(tempDir, "shot.png");
  await fs.writeFile(uploadPath, "fixture");

  const commands: Array<[CommandName, string[]]> = [
    ["open", ["open", "https://example.test"]],
    ["tabs", ["tabs"]],
    ["focus", ["focus", "t0"]],
    ["close", ["close", "t0"]],
    ["close-idle", ["close-idle", "--hours", "6", "--dry-run"]],
    ["click", ["click", "Continue"]],
    ["type", ["type", "Search", "browser"]],
    ["fill", ["fill", "Editor", "text"]],
    ["upload", ["upload", "input", uploadPath]],
    ["wait", ["wait", "--ms", "0"]],
    ["snapshot", ["snapshot"]],
    ["diff", ["diff"]],
    ["inspect", ["inspect"]],
    ["describe", ["describe"]],
    ["ask", ["ask", "what is visible?"]],
    ["extract", ["extract"]],
    ["screenshot", ["screenshot", screenshotPath]],
    ["html", ["html"]],
    ["eval", ["eval", "document.title"]],
    ["dialog", ["dialog"]],
    ["status", ["status"]],
    ["stop", ["stop"]],
  ];

  const bridge = new FakeBridge();
  let oracleCalls = 0;
  const fakeOracle: OracleRunner = async () => {
    oracleCalls += 1;
    return "offline oracle fixture";
  };

  try {
    for (const [expectedCommand, argv] of commands) {
      const request = requestFromArgv(argv, tempDir);
      assert.equal(request.command, expectedCommand);
      await assert.doesNotReject(runCommand(request, bridge, fakeOracle), `failed smoke command: ${expectedCommand}`);
    }

    assert.equal(oracleCalls, 2);
    assert.equal((await fs.readFile(screenshotPath)).length > 0, true);

    await runCommand({ command: "open", args: ["https://window.example"], options: { window: true } }, bridge, fakeOracle);
    const directWindowOpen = bridge.calls.filter(({ action }) => action === "open").at(-1);
    assert.equal(directWindowOpen?.params.newTab, true);
    assert.equal(directWindowOpen?.params.newWindow, true);
    const closeIdleCall = bridge.calls.find(({ action }) => action === "close-idle");
    assert.equal(closeIdleCall?.timeoutMs, CLOSE_IDLE_TIMEOUT_MS);
    const waitCall = bridge.calls.find(({ action }) => action === "wait");
    assert.equal(waitCall?.timeoutMs, 20_000);
    assert.equal(bridge.calls.some(({ action, timeoutMs }) => action === "status" && timeoutMs === 1_000), true);

    const dispatched = new Set(bridge.calls.map(({ action }) => action));
    for (const action of [
      "open", "tabs", "focus", "close", "close-idle", "click", "type", "fill", "upload", "wait", "snapshot", "diff",
      "inspect", "extract", "screenshot", "html", "eval", "dialog", "status",
    ] satisfies BridgeAction[]) {
      assert.equal(dispatched.has(action), true, `bridge action was not exercised: ${action}`);
    }
  } finally {
    await fs.rm(tempDir, { recursive: true, force: true });
  }
});
