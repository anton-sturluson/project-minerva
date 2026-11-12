import assert from "node:assert/strict";
import { test } from "node:test";
import type { TestContext } from "node:test";
import { runCommand } from "../src/server.js";
import type { CommandBridge } from "../src/server.js";

const MODEL = "accounts/fireworks/models/glm-5p3-flash";
const OPENAI = "https://api.openai.com/v1/responses";
const FIREWORKS = "https://api.fireworks.ai/inference/v1/chat/completions";
const OPENROUTER = "https://openrouter.ai/api/v1/chat/completions";

function fixture(t: TestContext, content: unknown = "Observed text", status = 200, finish = "stop") {
  process.env.OPENAI_API_KEY = "synthetic-openai-key";
  process.env.FIREWORKS_API_KEY = "synthetic-fireworks-key";
  process.env.OPENROUTER_API_KEY = "synthetic-openrouter-key";
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
    assert.equal(requests.length, 1, "No retries or fallback requests");
    return new Response(JSON.stringify(status === 200
      ? String(url) === OPENAI
        ? { status: finish === "stop" ? "completed" : "incomplete", output: [{ type: "message", content: [{ type: "output_text", text: content }] }] }
        : { choices: [{ finish_reason: finish, message: { content } }] }
      : { error: "synthetic-sensitive-marker" }), { status });
  });
  return { requests, actions, bridge };
}

test("oracle default uses Luna with screenshot and accessibility input", async (t) => {
  const { requests, actions, bridge } = fixture(t);
  const answer = await runCommand({ command: "ask", args: ["What is shown?"], options: {} }, bridge);
  assert.equal(answer, "Observed text");
  assert.deepEqual(actions, ["screenshot", "snapshot"]);
  assert.equal(requests[0]?.url, OPENAI);
  assert.equal(requests[0]?.headers.get("authorization"), "Bearer synthetic-openai-key");
  assert.equal(requests[0]?.body.model, "gpt-6-luna");
  assert.deepEqual(requests[0]?.body.reasoning, { effort: "high" });
  assert.equal(requests[0]?.body.store, false);
  assert.equal(requests[0]?.body.input[1].content[0].type, "input_text");
  assert.equal(requests[0]?.body.input[1].content[1].type, "input_image");
  assert.equal(requests[0]?.body.input[1].content[1].image_url, "data:image/jpeg;base64,synthetic");
});

test("explicit Fireworks vision keeps its route", async (t) => {
  const { requests, bridge } = fixture(t);
  assert.equal(await runCommand({ command: "describe", args: [], options: { model: MODEL } }, bridge), "Observed text");
  assert.equal(requests[0]?.url, FIREWORKS);
  assert.equal(requests[0]?.body.model, MODEL);
  assert.equal(requests[0]?.body.reasoning_effort, "high");
});

test("explicit OpenRouter vision ID keeps its exact host, key, model and image input", async (t) => {
  const { requests, actions, bridge } = fixture(t);
  const model = "google/gemini-3.1-flash-lite-preview";
  assert.equal(await runCommand({ command: "describe", args: [], options: { model } }, bridge), "Observed text");
  assert.deepEqual(actions, ["screenshot", "snapshot"]);
  assert.equal(requests[0]?.url, OPENROUTER);
  assert.equal(requests[0]?.headers.get("authorization"), "Bearer synthetic-openrouter-key");
  assert.equal(requests[0]?.body.model, model);
  assert.deepEqual(requests[0]?.body.provider, { allow_fallbacks: false });
  assert.equal(requests[0]?.body.models, undefined);
  assert.equal(requests[0]?.body.messages[1].content[1].type, "image_url");
});

test("text-only non-Flash GLM is rejected before image capture or a provider call", async (t) => {
  const { requests, actions, bridge } = fixture(t);
  await assert.rejects(
    runCommand({ command: "describe", args: [], options: { model: "fireworks/accounts/fireworks/models/glm-5p3" } }, bridge),
    /text-only.*requires image input.*No fallback/,
  );
  assert.equal(requests.length, 0);
  assert.deepEqual(actions, []);
});

test("missing Fireworks key cannot use an OpenRouter key or read a nearby env file", async (t) => {
  const { requests, actions, bridge } = fixture(t);
  delete process.env.FIREWORKS_API_KEY;
  await assert.rejects(runCommand({ command: "describe", args: [], options: { model: MODEL } }, bridge), /FIREWORKS_API_KEY is not set in the environment/);
  assert.equal(requests.length, 0);
  assert.deepEqual(actions, []);
});

test("OpenClaw account aliases cannot be sent to an arbitrary API host", async (t) => {
  const { requests, bridge } = fixture(t);
  await assert.rejects(runCommand({ command: "describe", args: [], options: { model: "openai-zdr/gpt-6.1-sol" } }, bridge), /OpenClaw account routes are unsupported/);
  assert.equal(requests.length, 0);
});

for (const status of [401, 429, 500]) {
  test(`provider HTTP ${status} is safe and never triggers fallback`, async (t) => {
    const { requests, bridge } = fixture(t, "unused", status);
    await assert.rejects(runCommand({ command: "describe", args: [], options: {} }, bridge), (error: Error) => {
      assert.match(error.message, new RegExp(`HTTP ${status}`));
      assert.doesNotMatch(error.message, /synthetic-sensitive-marker/);
      return true;
    });
    assert.equal(requests.length, 1);
  });
}

for (const [content, finish] of [["", "stop"], ["partial", "length"], [null, "content_filter"]]) {
  test(`empty or incomplete answer fails (${finish})`, async (t) => {
    const { requests, bridge } = fixture(t, content, 200, String(finish));
    await assert.rejects(runCommand({ command: "describe", args: [], options: {} }, bridge), /did not include text|incomplete answer/);
    assert.equal(requests.length, 1);
  });
}

test("network errors cannot expose request headers", async (t) => {
  const { bridge } = fixture(t);
  t.mock.method(globalThis, "fetch", async () => { throw new TypeError("synthetic-sensitive-marker"); });
  await assert.rejects(runCommand({ command: "describe", args: [], options: {} }, bridge), (error: Error) => {
    assert.doesNotMatch(error.message, /synthetic-sensitive-marker/);
    assert.match(error.message, /network error/);
    return true;
  });
});


test("invalid Fireworks-qualified GPT model never sends the screenshot to OpenAI", async (t) => {
  const { requests, actions, bridge } = fixture(t);
  await assert.rejects(
    runCommand({ command: "describe", args: [], options: { model: "fireworks/gpt-6-luna" } }, bridge),
    /valid Fireworks model ID.*No fallback/,
  );
  assert.equal(requests.length, 0);
  assert.deepEqual(actions, []);
});
