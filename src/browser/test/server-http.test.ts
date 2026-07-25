import assert from "node:assert/strict";
import http from "node:http";
import { test } from "node:test";
import { createRequestHandler, type CommandExecutor } from "../src/server.js";
import type { CommandResponse } from "../src/lib/types.js";

interface TestResponse {
  statusCode: number;
  body: CommandResponse;
}

function postCommand(port: number, headers: http.OutgoingHttpHeaders, body: string): Promise<TestResponse> {
  return new Promise((resolve, reject) => {
    const request = http.request(
      {
        method: "POST",
        host: "127.0.0.1",
        port,
        path: "/command",
        headers: {
          "content-length": Buffer.byteLength(body),
          ...headers,
        },
      },
      (response) => {
        const chunks: Buffer[] = [];
        response.on("data", (chunk) => chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk)));
        response.on("end", () => {
          try {
            resolve({
              statusCode: response.statusCode ?? 0,
              body: JSON.parse(Buffer.concat(chunks).toString("utf8")) as CommandResponse,
            });
          } catch (error) {
            reject(error);
          }
        });
      },
    );
    request.on("error", reject);
    request.end(body);
  });
}

test("loopback command endpoint rejects browser-compatible requests before dispatch", async () => {
  const dispatched: string[] = [];
  const executor: CommandExecutor = async (body) => {
    dispatched.push(body.command);
    return {
      ok: true,
      data: [],
      url: "about:blank",
      title: "",
      elapsed: 0,
    };
  };
  const server = http.createServer(createRequestHandler(executor));
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  assert.ok(address && typeof address === "object");

  try {
    const noCorsStyle = await postCommand(address.port, { "content-type": "text/plain" }, "not json");
    assert.equal(noCorsStyle.statusCode, 415);
    assert.match(noCorsStyle.body.error ?? "", /application\/json/);
    assert.deepEqual(dispatched, []);

    const originBearing = await postCommand(
      address.port,
      { "content-type": "application/json", origin: "https://attacker.example" },
      "not json",
    );
    assert.equal(originBearing.statusCode, 403);
    assert.match(originBearing.body.error ?? "", /Browser-origin/);
    assert.deepEqual(dispatched, []);

    const cliStyle = await postCommand(
      address.port,
      { "content-type": "application/json" },
      JSON.stringify({ command: "tabs", args: [], options: {} }),
    );
    assert.equal(cliStyle.statusCode, 200);
    assert.equal(cliStyle.body.ok, true);
    assert.deepEqual(dispatched, ["tabs"]);
  } finally {
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }
});
