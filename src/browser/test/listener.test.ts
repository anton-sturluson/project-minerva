import assert from "node:assert/strict";
import fs from "node:fs/promises";
import http from "node:http";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { listenForCommands } from "../src/lib/listener.js";

async function unusedPort(): Promise<number> {
  const server = net.createServer();
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  assert.ok(address && typeof address === "object");
  await new Promise<void>((resolve) => server.close(() => resolve()));
  return address.port;
}

function commandServer(): http.Server {
  return http.createServer((request, response) => {
    if (request.url === "/health") {
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ service: "browser-cli", ok: true }));
      return;
    }
    response.writeHead(404).end();
  });
}

test("simultaneous cold starts converge on one Unix command listener", async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "browser-listener-"));
  const socketPath = path.join(directory, "command.sock");
  const fallbackPort = await unusedPort();
  const first = commandServer();
  const second = commandServer();

  try {
    const results = await Promise.all([
      listenForCommands(first, { socketPath, fallbackPort }),
      listenForCommands(second, { socketPath, fallbackPort }),
    ]);
    assert.deepEqual(results.map((result) => result.transport).sort(), ["existing", "socket"]);
    assert.equal([first, second].filter((candidate) => candidate.listening).length, 1);
  } finally {
    await Promise.all(
      [first, second].map((candidate) =>
        candidate.listening ? new Promise<void>((resolve) => candidate.close(() => resolve())) : Promise.resolve(),
      ),
    );
    await fs.rm(directory, { recursive: true, force: true });
  }
});

test("a live non-Browser service at the socket path is never unlinked", async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "browser-listener-"));
  const socketPath = path.join(directory, "command.sock");
  const fallbackPort = await unusedPort();
  const occupant = http.createServer((_request, response) => response.writeHead(200).end("not browser"));
  const candidate = commandServer();
  await new Promise<void>((resolve, reject) => {
    occupant.once("error", reject);
    occupant.listen(socketPath, resolve);
  });

  try {
    await assert.rejects(
      listenForCommands(candidate, { socketPath, fallbackPort }),
      /occupied by another live service/,
    );
    assert.equal(occupant.listening, true);
    assert.equal((await fs.lstat(socketPath)).isSocket(), true);
  } finally {
    await new Promise<void>((resolve) => occupant.close(() => resolve()));
    await fs.rm(directory, { recursive: true, force: true });
  }
});
