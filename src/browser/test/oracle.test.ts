import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { test } from "node:test";
import type { TestContext } from "node:test";
import { runCommand } from "../src/server.js";
import type { CommandBridge } from "../src/server.js";

const OPENAI = "https://api.openai.com/v1/responses";
const OPENROUTER = "https://openrouter.ai/api/v1/chat/completions";

function fixture(t: TestContext, payload?: unknown) {
  const previousOpenAI = process.env.OPENAI_API_KEY;
  const previousOpenRouter = process.env.OPENROUTER_API_KEY;
  process.env.OPENAI_API_KEY = "synthetic-openai-key";
  process.env.OPENROUTER_API_KEY = "synthetic-openrouter-key";
  t.after(() => {
    if (previousOpenAI === undefined) delete process.env.OPENAI_API_KEY;
    else process.env.OPENAI_API_KEY = previousOpenAI;
    if (previousOpenRouter === undefined) delete process.env.OPENROUTER_API_KEY;
    else process.env.OPENROUTER_API_KEY = previousOpenRouter;
  });
  const requests: Array<{ url: string; body: Record<string, any>; headers: Headers }> = [];
  const actions: string[] = [];
  const bridge: CommandBridge = {
    getStatus: () => ({ connected: true }),
    call: async (action) => {
      actions.push(action);
      if (action === "snapshot") return { snapshot: "button Continue" };
      if (action === "screenshot") return { tabId: 7, dataUrl: "data:image/jpeg;base64,synthetic" };
      throw new Error("Unplanned bridge action");
    },
  };
  t.mock.method(globalThis, "fetch", async (url: string | URL | Request, init?: RequestInit) => {
    requests.push({ url: String(url), body: JSON.parse(String(init?.body)), headers: new Headers(init?.headers) });
    assert.equal(requests.length, 1, "No retries or provider fallback");
    const value = payload ?? (String(url) === OPENAI
      ? { status: "completed", output: [{ type: "message", content: [{ type: "output_text", text: "Observed text" }] }] }
      : { choices: [{ finish_reason: "stop", message: { content: "Observed text" } }] });
    return new Response(JSON.stringify(value), { status: 200 });
  });
  return { requests, actions, bridge };
}

test("default oracle sends screenshot and accessibility tree to Luna 6", async (t) => {
  const { requests, actions, bridge } = fixture(t);
  const answer = await runCommand({ command: "ask", args: ["What is shown?"], options: {} }, bridge);
  assert.equal(answer, "Observed text");
  assert.deepEqual(actions, ["screenshot", "snapshot"]);
  assert.equal(requests[0]?.url, OPENAI);
  assert.equal(requests[0]?.headers.get("authorization"), "Bearer synthetic-openai-key");
  assert.equal(requests[0]?.body.model, "gpt-6-luna");
  assert.deepEqual(requests[0]?.body.reasoning, { effort: "high" });
  assert.equal(requests[0]?.body.store, false);
  assert.match(requests[0]?.body.input[1].content[0].text, /button Continue/);
  assert.equal(requests[0]?.body.input[1].content[1].type, "input_image");
  assert.equal(requests[0]?.body.input[1].content[1].image_url, "data:image/jpeg;base64,synthetic");
});

test("explicit OpenRouter model retains its original host, model and image input", async (t) => {
  const { requests, actions, bridge } = fixture(t);
  const model = "google/gemini-3.1-flash-lite-preview";
  assert.equal(await runCommand({ command: "describe", args: [], options: { model } }, bridge), "Observed text");
  assert.deepEqual(actions, ["screenshot", "snapshot"]);
  assert.equal(requests[0]?.url, OPENROUTER);
  assert.equal(requests[0]?.headers.get("authorization"), "Bearer synthetic-openrouter-key");
  assert.equal(requests[0]?.body.model, model);
  assert.equal(requests[0]?.body.messages[1].content[1].type, "image_url");
});

test("OpenClaw account routes are not sent to another provider", async (t) => {
  const { requests, actions, bridge } = fixture(t);
  await assert.rejects(
    runCommand({ command: "describe", args: [], options: { model: "openai-zdr/gpt-6.1-sol" } }, bridge),
    /OpenClaw account routes are unsupported/,
  );
  assert.deepEqual(actions, []);
  assert.equal(requests.length, 0);
});

for (const [name, payload] of [
  ["incomplete", { status: "incomplete", output: [{ type: "message", content: [{ type: "output_text", text: "partial" }] }] }],
  ["refusal", { status: "completed", output: [{ type: "message", content: [{ type: "output_text", text: "partial" }, { type: "refusal", refusal: "no" }] }] }],
] as const) {
  test(`Luna ${name} does not return partial text`, async (t) => {
    const { requests, bridge } = fixture(t, payload);
    await assert.rejects(runCommand({ command: "describe", args: [], options: {} }, bridge), /incomplete answer or refusal/);
    assert.equal(requests.length, 1);
  });
}

test("incomplete OpenRouter response is rejected", async (t) => {
  const { requests, bridge } = fixture(t, { choices: [{ finish_reason: "length", message: { content: "partial" } }] });
  await assert.rejects(
    runCommand({ command: "describe", args: [], options: { model: "google/gemini-3.1-flash-lite-preview" } }, bridge),
    /incomplete answer or refusal/,
  );
  assert.equal(requests.length, 1);
});

test("missing OpenAI key fails before capturing a screenshot", async (t) => {
  const { requests, actions, bridge } = fixture(t);
  delete process.env.OPENAI_API_KEY;
  await assert.rejects(runCommand({ command: "describe", args: [], options: {} }, bridge), /OPENAI_API_KEY is not set/);
  assert.deepEqual(actions, []);
  assert.equal(requests.length, 0);
});


test("explicit OpenRouter route still reads a nearby .env key", async (t) => {
  const { requests, bridge } = fixture(t);
  const previousDir = process.cwd();
  const dir = mkdtempSync(path.join(tmpdir(), "browser-oracle-test-"));
  t.after(() => { process.chdir(previousDir); rmSync(dir, { recursive: true, force: true }); });
  writeFileSync(path.join(dir, ".env"), "OPENROUTER_API_KEY=synthetic-env-key\n");
  delete process.env.OPENROUTER_API_KEY;
  process.chdir(dir);
  assert.equal(await runCommand({ command: "describe", args: [], options: { model: "google/gemini-3.1-flash-lite-preview" } }, bridge), "Observed text");
  assert.equal(requests[0]?.headers.get("authorization"), "Bearer synthetic-env-key");
});

test("OpenRouter refusal parts cannot be returned with partial text", async (t) => {
  const { bridge } = fixture(t, { choices: [{ finish_reason: "stop", message: { content: [{ type: "text", text: "partial" }, { type: "refusal", refusal: "no" }] } }] });
  await assert.rejects(
    runCommand({ command: "describe", args: [], options: { model: "google/gemini-3.1-flash-lite-preview" } }, bridge),
    /incomplete answer or refusal/,
  );
});
