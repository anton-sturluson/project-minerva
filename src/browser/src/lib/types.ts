export const SOCKET_PATH = "/tmp/browser-cli-v2.sock";
export const FALLBACK_PORT = 19223;
export const BRIDGE_WS_PORT = 19224;
export const DEFAULT_TIMEOUT_MS = 30_000;
export const BRIDGE_TIMEOUT_GRACE_MS = 5_000;
export const CLOSE_IDLE_TIMEOUT_MS = 120_000;
export const OUTPUT_LINE_LIMIT = 200;
export const OPEN_PREVIEW_CHARS = 500;
export const DEFAULT_EXTRACT_LIMIT = 20;
export const DEFAULT_HTML_LIMIT = 120;

export type CommandName =
  | "open"
  | "tabs"
  | "focus"
  | "close"
  | "close-idle"
  | "click"
  | "type"
  | "fill"
  | "upload"
  | "wait"
  | "snapshot"
  | "diff"
  | "inspect"
  | "describe"
  | "ask"
  | "extract"
  | "screenshot"
  | "html"
  | "eval"
  | "dialog"
  | "status"
  | "stop";

export interface CommandRequest {
  command: CommandName;
  args: string[];
  options: Record<string, unknown>;
}

export interface CommandResponse {
  ok: boolean;
  data?: unknown;
  error?: string;
  url: string;
  title: string;
  elapsed: number;
}

export interface BrowserState {
  startedAt: number;
}

export type BridgeAction =
  | "open"
  | "tabs"
  | "focus"
  | "close"
  | "close-idle"
  | "click"
  | "type"
  | "fill"
  | "upload"
  | "wait"
  | "snapshot"
  | "diff"
  | "inspect"
  | "extract"
  | "screenshot"
  | "html"
  | "eval"
  | "dialog"
  | "status";

export interface BridgeRequest {
  id: string;
  action: BridgeAction;
  params: Record<string, unknown>;
  deadline: number;
}

export interface BridgeCancelRequest {
  type: "cancel";
  id: string;
}

export interface BridgeResponse {
  id: string;
  ok: boolean;
  data?: unknown;
  error?: string;
}

export interface BridgeHelloMessage {
  type: "hello";
  source?: string;
}

export class FriendlyError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "FriendlyError";
  }
}
