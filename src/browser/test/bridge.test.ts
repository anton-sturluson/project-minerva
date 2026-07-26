import assert from "node:assert/strict";
import net from "node:net";
import { test } from "node:test";
import { WebSocket } from "ws";
import { ExtensionBridge } from "../src/lib/bridge.js";

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

function openSocket(port: number, origin = "chrome-extension://test-extension"): Promise<WebSocket> {
  return new Promise((resolve, reject) => {
    const socket = new WebSocket(`ws://127.0.0.1:${port}`, { origin });
    socket.once("open", () => resolve(socket));
    socket.once("error", reject);
  });
}

function closeSocket(socket: WebSocket): Promise<void> {
  if (socket.readyState === WebSocket.CLOSED) return Promise.resolve();
  return new Promise((resolve) => {
    socket.once("close", () => resolve());
    socket.close();
  });
}

const validHello = {
  type: "hello",
  source: "browser-cli-extension",
  protocolVersion: 1,
};

test("bridge promotes only a valid extension hello and ignores unauthenticated replacements", async () => {
  const port = await unusedPort();
  const bridge = new ExtensionBridge({ port, handshakeTimeoutMs: 100 });
  await bridge.ready();
  const first = await openSocket(port);
  const candidate = await openSocket(port);

  try {
    assert.equal(bridge.getStatus().connected, false);
    first.send(JSON.stringify(validHello));
    await new Promise((resolve) => setTimeout(resolve, 10));
    assert.equal(bridge.getStatus().connected, true);

    await new Promise((resolve) => setTimeout(resolve, 130));
    assert.equal(candidate.readyState, WebSocket.CLOSED);
    assert.equal(bridge.getStatus().connected, true, "timed-out candidate must not replace the real extension");

    first.once("message", (raw) => {
      const request = JSON.parse(raw.toString()) as { id: string };
      first.send(JSON.stringify({ id: request.id, ok: true, data: "ok" }));
    });
    assert.equal(await bridge.call("tabs", {}, 500), "ok");
  } finally {
    await Promise.all([closeSocket(first), closeSocket(candidate)]);
    await bridge.close();
  }
});

test("aborting a bridge call sends extension cancellation immediately", async () => {
  const port = await unusedPort();
  const bridge = new ExtensionBridge({ port });
  await bridge.ready();
  const extension = await openSocket(port);
  extension.send(JSON.stringify(validHello));
  await new Promise((resolve) => setTimeout(resolve, 10));
  const cancellationSeen = new Promise<{ type: string; id: string }>((resolve) => {
    extension.on("message", (raw) => {
      const payload = JSON.parse(raw.toString()) as { type?: string; id: string };
      if (payload.type === "cancel") resolve({ type: payload.type, id: payload.id });
    });
  });
  const controller = new AbortController();
  const call = bridge.call("wait", {}, 10_000, controller.signal);
  controller.abort();
  try {
    await assert.rejects(call, /cancelled/);
    assert.equal((await cancellationSeen).type, "cancel");
  } finally {
    await closeSocket(extension);
    await bridge.close();
  }
});

test("fixed bridge-port conflicts reject cleanly", async () => {
  const port = await unusedPort();
  const winner = new ExtensionBridge({ port });
  await winner.ready();
  const loser = new ExtensionBridge({ port });
  try {
    await assert.rejects(loser.ready(), (error: NodeJS.ErrnoException) => error.code === "EADDRINUSE");
  } finally {
    await loser.close();
    await winner.close();
  }
});

test("bridge rejects normal web-page websocket origins", async () => {
  const port = await unusedPort();
  const bridge = new ExtensionBridge({ port });
  await bridge.ready();
  try {
    await assert.rejects(openSocket(port, "https://example.test"), /403|Unexpected server response/);
    assert.equal(bridge.getStatus().connected, false);
  } finally {
    await bridge.close();
  }
});

test("bridge rejects stale extension protocol handshakes", async () => {
  const port = await unusedPort();
  const bridge = new ExtensionBridge({ port });
  await bridge.ready();
  const staleExtension = await openSocket(port);
  staleExtension.send(JSON.stringify({
    type: "hello",
    source: "browser-cli-v2-extension",
  }));

  try {
    await new Promise<void>((resolve) => staleExtension.once("close", () => resolve()));
    assert.equal(bridge.getStatus().connected, false);
  } finally {
    await bridge.close();
  }
});
