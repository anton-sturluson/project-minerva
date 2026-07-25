import { randomUUID } from "node:crypto";
import { WebSocket, WebSocketServer, type RawData } from "ws";
import { BRIDGE_WS_PORT, DEFAULT_TIMEOUT_MS, FriendlyError } from "./types.js";
import type { BridgeAction, BridgeCancelRequest, BridgeHelloMessage, BridgeRequest, BridgeResponse } from "./types.js";

interface PendingRequest {
  resolve: (value: unknown) => void;
  reject: (reason: Error) => void;
  timer: NodeJS.Timeout;
  cleanupAbort: () => void;
}

export interface ExtensionBridgeOptions {
  host?: string;
  port?: number;
  handshakeTimeoutMs?: number;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isHelloMessage(value: unknown): value is BridgeHelloMessage {
  return isObject(value) && value.type === "hello" && value.source === "browser-cli-v2-extension";
}

function isBridgeResponse(value: unknown): value is BridgeResponse {
  return isObject(value) && typeof value.id === "string" && typeof value.ok === "boolean";
}

function parseMessage(payload: RawData): unknown {
  try {
    return JSON.parse(payload.toString()) as unknown;
  } catch {
    return null;
  }
}

export class ExtensionBridge {
  private readonly wss: WebSocketServer;
  private readonly readyPromise: Promise<void>;
  private readonly handshakeTimeoutMs: number;
  private readonly candidates = new Map<WebSocket, NodeJS.Timeout>();
  private extensionSocket: WebSocket | null = null;
  private readonly pending = new Map<string, PendingRequest>();
  private readonly requestPrefix = randomUUID();
  private requestCounter = 0;
  private lastSeenAt: number | null = null;

  constructor(options: ExtensionBridgeOptions = {}) {
    this.handshakeTimeoutMs = options.handshakeTimeoutMs ?? 3_000;
    this.wss = new WebSocketServer({
      host: options.host ?? "127.0.0.1",
      port: options.port ?? BRIDGE_WS_PORT,
      verifyClient: ({ origin }, done) => {
        // A browser page must not be able to impersonate the unpacked extension.
        // Chrome extension service workers send their chrome-extension:// origin.
        done(typeof origin === "string" && origin.startsWith("chrome-extension://"), 403, "Extension origin required");
      },
    });

    this.readyPromise = new Promise((resolve, reject) => {
      this.wss.once("listening", resolve);
      this.wss.once("error", reject);
    });
    // Keep later server errors from becoming uncaught EventEmitter errors.
    this.wss.on("error", () => undefined);
    this.wss.on("connection", (socket) => this.attachCandidate(socket));
  }

  ready(): Promise<void> {
    return this.readyPromise;
  }

  isConnected(): boolean {
    return this.extensionSocket?.readyState === WebSocket.OPEN;
  }

  getStatus() {
    return { connected: this.isConnected(), lastSeenAt: this.lastSeenAt };
  }

  private attachCandidate(socket: WebSocket) {
    const timer = setTimeout(() => {
      this.candidates.delete(socket);
      socket.close(1008, "Extension hello timed out");
    }, this.handshakeTimeoutMs);
    this.candidates.set(socket, timer);

    socket.on("message", (message) => {
      const parsed = parseMessage(message);
      if (socket !== this.extensionSocket) {
        if (isHelloMessage(parsed)) {
          this.promoteCandidate(socket);
        } else {
          clearTimeout(timer);
          this.candidates.delete(socket);
          socket.close(1008, "Valid extension hello required");
        }
        return;
      }
      this.onAuthenticatedMessage(parsed);
    });

    socket.on("close", () => {
      const candidateTimer = this.candidates.get(socket);
      if (candidateTimer) clearTimeout(candidateTimer);
      this.candidates.delete(socket);
      if (this.extensionSocket === socket) {
        this.extensionSocket = null;
        this.rejectAllPending("Chrome extension bridge disconnected during command execution.");
      }
    });
    socket.on("error", () => undefined);
  }

  private promoteCandidate(socket: WebSocket) {
    const timer = this.candidates.get(socket);
    if (timer) clearTimeout(timer);
    this.candidates.delete(socket);

    const previous = this.extensionSocket;
    if (previous && previous !== socket && previous.readyState === WebSocket.OPEN) {
      this.rejectAllPending("Chrome extension bridge reconnected during command execution. Retry the command.");
      previous.close(1012, "Replaced by an authenticated extension connection");
    }
    this.extensionSocket = socket;
    this.lastSeenAt = Date.now();
  }

  private onAuthenticatedMessage(parsed: unknown) {
    this.lastSeenAt = Date.now();
    if (isObject(parsed) && parsed.type === "keepalive") {
      return;
    }
    if (!isBridgeResponse(parsed)) return;

    const pending = this.pending.get(parsed.id);
    if (!pending) return;
    clearTimeout(pending.timer);
    pending.cleanupAbort();
    this.pending.delete(parsed.id);
    if (parsed.ok) pending.resolve(parsed.data);
    else pending.reject(new FriendlyError(parsed.error ?? "Extension command failed."));
  }

  async call(
    action: BridgeAction,
    params: Record<string, unknown>,
    timeoutMs = DEFAULT_TIMEOUT_MS,
    signal?: AbortSignal,
  ): Promise<unknown> {
    if (signal?.aborted) {
      throw new FriendlyError(`Command cancelled before extension request (${action}).`);
    }
    if (!this.extensionSocket || this.extensionSocket.readyState !== WebSocket.OPEN) {
      throw new FriendlyError(
        "Chrome extension bridge is not connected. Load the extension from src/browser/extension and keep a Chrome tab open.",
      );
    }

    const id = `${this.requestPrefix}:${this.requestCounter++}`;
    const socket = this.extensionSocket;
    const request: BridgeRequest = { id, action, params, deadline: Date.now() + timeoutMs };

    return new Promise((resolve, reject) => {
      const sendCancellation = () => {
        if (socket.readyState === WebSocket.OPEN) {
          const cancellation: BridgeCancelRequest = { type: "cancel", id };
          try {
            socket.send(JSON.stringify(cancellation), () => undefined);
          } catch {
            // The socket raced closed; disconnect is also treated as cancellation.
          }
        }
      };
      const onAbort = () => {
        const pending = this.pending.get(id);
        if (!pending) return;
        clearTimeout(pending.timer);
        pending.cleanupAbort();
        this.pending.delete(id);
        sendCancellation();
        reject(new FriendlyError(`Command cancelled while waiting for extension response (${action}).`));
      };
      const cleanupAbort = () => signal?.removeEventListener("abort", onAbort);
      const timer = setTimeout(() => {
        cleanupAbort();
        this.pending.delete(id);
        sendCancellation();
        reject(new FriendlyError(`Timed out waiting for extension response (${action}).`));
      }, timeoutMs);

      this.pending.set(id, { resolve, reject, timer, cleanupAbort });
      signal?.addEventListener("abort", onAbort, { once: true });
      try {
        socket.send(JSON.stringify(request));
      } catch {
        clearTimeout(timer);
        cleanupAbort();
        this.pending.delete(id);
        reject(new FriendlyError("Failed to send command to Chrome extension bridge."));
      }
    });
  }

  private rejectAllPending(message: string) {
    for (const [id, pending] of this.pending.entries()) {
      clearTimeout(pending.timer);
      pending.cleanupAbort();
      pending.reject(new FriendlyError(message));
      this.pending.delete(id);
    }
  }

  async close(): Promise<void> {
    this.rejectAllPending("Browser bridge server is shutting down.");
    for (const [candidate, timer] of this.candidates) {
      clearTimeout(timer);
      candidate.close(1001, "Server shutting down");
    }
    this.candidates.clear();
    if (this.extensionSocket?.readyState === WebSocket.OPEN) {
      this.extensionSocket.close(1001, "Server shutting down");
    }
    this.extensionSocket = null;

    await new Promise<void>((resolve) => {
      try {
        this.wss.close(() => resolve());
      } catch {
        resolve();
      }
    });
  }
}
