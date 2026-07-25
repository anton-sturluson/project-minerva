import http from "node:http";
import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { pathToFileURL } from "node:url";
import { ExtensionBridge } from "./lib/bridge.js";
import { listenForCommands } from "./lib/listener.js";
import { validateCommandInput } from "./lib/parse.js";
import { BRIDGE_TIMEOUT_GRACE_MS, BRIDGE_WS_PORT, CLOSE_IDLE_TIMEOUT_MS, DEFAULT_EXTRACT_LIMIT, DEFAULT_HTML_LIMIT, FALLBACK_PORT, FriendlyError, SOCKET_PATH } from "./lib/types.js";
import type { BridgeAction, BrowserState, CommandName, CommandRequest, CommandResponse } from "./lib/types.js";

const DEFAULT_ORACLE_MODEL = "google/gemini-3.1-flash-lite-preview";
const LOCATION_TIMEOUT_MS = 1_000;
const OPENROUTER_TIMEOUT_MS = 60_000;

const DESCRIBE_SYSTEM_PROMPT = `You are a browser state oracle inside a browser automation tool.
You receive a screenshot and an accessibility tree of a web page.

Describe everything you observe on this page. Be thorough - anything a
human would notice when looking at this page should be mentioned. Include:

- What the page is showing (main content, current view or section)
- Any modal, dialog, banner, toast, or overlay that is visible
- State of interactive elements if relevant (toggles, inputs, selections)
- Any error messages, warnings, or loading states
- Anything unusual or unexpected

Report what you see verbatim. Quote exact text from the page - do not
paraphrase error messages, labels, button text, or status indicators.
If a banner says "Content under review", write exactly that, not a summary.

Be concise but never omit observations to save space. If the page is
complex, a longer response is correct. If it's simple, a short one is fine.
Plain text, no markdown formatting.`;

const ASK_SYSTEM_PROMPT = `You are a browser state oracle inside a browser automation tool.
You receive a screenshot, an accessibility tree of a web page, and a
specific question.

Answer the question precisely and factually based on what you can observe
in the screenshot and accessibility tree.

Report what you see verbatim. Quote exact text from the page - do not
paraphrase or summarize labels, messages, values, or button text.
If the page says "144/4000", report exactly "144/4000", not "about 144
characters."

Never guess. If you cannot determine the answer from what's visible,
say "unclear from current view" and explain what you can see instead.

Plain text, 1-5 sentences. Be concise but precise.`;

const COMMAND_NAMES: ReadonlySet<CommandName> = new Set([
  "open",
  "tabs",
  "focus",
  "close",
  "close-idle",
  "click",
  "type",
  "fill",
  "upload",
  "wait",
  "snapshot",
  "diff",
  "inspect",
  "describe",
  "ask",
  "extract",
  "screenshot",
  "html",
  "eval",
  "dialog",
  "status",
  "stop",
]);

const state: BrowserState = {
  startedAt: Date.now(),
};

export interface CommandBridge {
  call(action: BridgeAction, params: Record<string, unknown>, timeoutMs?: number, signal?: AbortSignal): Promise<unknown>;
  getStatus(): { connected: boolean; lastSeenAt?: number | null };
}

type OracleParams = { prompt: string; question?: string; scope?: string; model?: string; tabId?: string };
export type OracleRunner = (params: OracleParams, commandBridge: CommandBridge) => Promise<string>;

let bridge: ExtensionBridge | null = null;
let server: http.Server | null = null;
let ownsSocket = false;
let shuttingDown = false;

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function parseString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function parseNumberOption(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function buildTabParams(options: Record<string, unknown>): Record<string, unknown> {
  return typeof options.tab === "string" && options.tab.trim() ? { tabId: options.tab.trim() } : {};
}

function extractLocation(value: unknown): { url: string; title: string } | null {
  if (!isObject(value)) {
    return null;
  }

  const url = parseString(value.url);
  if (!url) {
    return null;
  }

  return {
    url,
    title: parseString(value.title),
  };
}

function requireBridge(): ExtensionBridge {
  if (!bridge) {
    throw new FriendlyError("Browser server has not started its extension bridge.");
  }
  return bridge;
}

async function getCurrentLocation(commandBridge: CommandBridge): Promise<{ url: string; title: string }> {
  try {
    const status = await commandBridge.call("status", {}, LOCATION_TIMEOUT_MS);
    const location = extractLocation(status);
    if (location) {
      return location;
    }
  } catch {
    // fall through
  }

  return { url: "about:blank", title: "" };
}

function parseEnvValue(raw: string): string {
  const trimmed = raw.trim();
  if (
    (trimmed.startsWith('"') && trimmed.endsWith('"')) ||
    (trimmed.startsWith("'") && trimmed.endsWith("'"))
  ) {
    return trimmed.slice(1, -1);
  }
  return trimmed;
}

async function readEnvFile(envPath: string): Promise<Record<string, string>> {
  try {
    const content = await fs.readFile(envPath, "utf8");
    const entries: Record<string, string> = {};
    for (const line of content.split(/\r?\n/)) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith("#")) {
        continue;
      }
      const separatorIndex = trimmed.indexOf("=");
      if (separatorIndex === -1) {
        continue;
      }
      const key = trimmed.slice(0, separatorIndex).trim();
      const value = trimmed.slice(separatorIndex + 1);
      if (key) {
        entries[key] = parseEnvValue(value);
      }
    }
    return entries;
  } catch {
    return {};
  }
}

async function loadApiKey(): Promise<string> {
  if (process.env.OPENROUTER_API_KEY) {
    return process.env.OPENROUTER_API_KEY;
  }

  const candidatePaths = [
    path.resolve(process.cwd(), ".env"),
    path.resolve(process.cwd(), "..", ".env"),
    path.resolve(process.cwd(), "..", "..", ".env"),
  ];

  for (const envPath of candidatePaths) {
    const values = await readEnvFile(envPath);
    if (values.OPENROUTER_API_KEY) {
      return values.OPENROUTER_API_KEY;
    }
  }

  throw new FriendlyError("OPENROUTER_API_KEY is not set. Set it in the environment or in the .env file.");
}

function extractChatText(payload: unknown): string {
  if (!isObject(payload) || !Array.isArray(payload.choices) || payload.choices.length === 0) {
    throw new FriendlyError("API response did not include any choices.");
  }

  const firstChoice = payload.choices[0];
  if (!isObject(firstChoice) || !isObject(firstChoice.message)) {
    throw new FriendlyError("API response did not include a message.");
  }

  const content = firstChoice.message.content;
  if (typeof content === "string") {
    return content.trim();
  }

  if (Array.isArray(content)) {
    const text = content
      .map((part) => {
        if (!isObject(part)) {
          return "";
        }
        if (typeof part.text === "string") {
          return part.text;
        }
        return "";
      })
      .join("\n")
      .trim();
    if (text) {
      return text;
    }
  }

  throw new FriendlyError("API response did not include text content.");
}

async function runOracle(params: OracleParams, commandBridge: CommandBridge): Promise<string> {
  try {
    // Extension requests are intentionally serialized, so capture these in
    // sequence and give each operation its own full timeout budget.
    const screenshotResult = await commandBridge.call(
      "screenshot",
      { maxWidth: 1280, quality: 70, format: "jpeg", ...(params.tabId ? { tabId: params.tabId } : {}) },
      30_000,
    );
    const capturedTabId = isObject(screenshotResult) && Number.isInteger(screenshotResult.tabId)
      ? screenshotResult.tabId
      : params.tabId;
    const snapshotResult = await commandBridge.call(
      "snapshot",
      { scope: params.scope ?? null, ...(capturedTabId != null ? { tabId: capturedTabId } : {}) },
      30_000,
    );

    if (!isObject(screenshotResult) || typeof screenshotResult.dataUrl !== "string") {
      throw new FriendlyError("Extension did not return screenshot data.");
    }
    if (!isObject(snapshotResult) || typeof snapshotResult.snapshot !== "string") {
      throw new FriendlyError("Extension did not return snapshot data.");
    }

    const apiKey = await loadApiKey();
    const model = params.model || DEFAULT_ORACLE_MODEL;
    const userText = params.question
      ? `Accessibility tree:\n${snapshotResult.snapshot}\n\nQuestion:\n${params.question}`
      : `Accessibility tree:\n${snapshotResult.snapshot}`;

    const response = await fetch("https://openrouter.ai/api/v1/chat/completions", {
      method: "POST",
      signal: AbortSignal.timeout(OPENROUTER_TIMEOUT_MS),
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model,
        messages: [
          { role: "system", content: params.prompt },
          {
            role: "user",
            content: [
              { type: "text", text: userText },
              { type: "image_url", image_url: { url: screenshotResult.dataUrl } },
            ],
          },
        ],
      }),
    });

    if (!response.ok) {
      const details = (await response.text().catch(() => "")).slice(0, 500);
      throw new FriendlyError(`OpenRouter request failed (${response.status} ${response.statusText})${details ? `: ${details}` : ""}`);
    }

    const payload = (await response.json()) as unknown;
    return extractChatText(payload);
  } catch (error) {
    if (error instanceof FriendlyError) {
      throw error;
    }
    if (error instanceof DOMException && error.name === "TimeoutError") {
      throw new FriendlyError(`OpenRouter request timed out after ${OPENROUTER_TIMEOUT_MS / 1000}s.`);
    }
    if (error instanceof TypeError) {
      throw new FriendlyError(`Oracle request failed (network error: ${error.message}). Check connectivity and OPENROUTER_API_KEY.`);
    }
    const message = error instanceof Error ? error.message : String(error);
    throw new FriendlyError(`Oracle failed unexpectedly: ${message}`);
  }
}

async function closeResources() {
  await bridge?.close().catch(() => undefined);
  bridge = null;
}

async function shutdown() {
  if (shuttingDown) {
    return;
  }

  shuttingDown = true;
  await closeResources();

  if (server) {
    await new Promise<void>((resolve) => {
      server?.close(() => resolve());
    });
  }

  if (ownsSocket) {
    await fs.rm(SOCKET_PATH, { force: true }).catch(() => undefined);
    ownsSocket = false;
  }
}

async function parseJsonBody(request: http.IncomingMessage): Promise<unknown> {
  const chunks: Buffer[] = [];
  for await (const chunk of request) {
    chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
  }
  const payload = Buffer.concat(chunks).toString("utf8");
  return payload ? JSON.parse(payload) : {};
}

export async function runCommand(
  body: CommandRequest,
  commandBridge: CommandBridge,
  oracleRunner: OracleRunner = runOracle,
): Promise<unknown> {
  const { command, args, options } = body;
  const validationIssue = validateCommandInput(command, args, options);
  if (validationIssue) {
    throw new FriendlyError(validationIssue);
  }

  switch (command) {
    case "open": {
      const [url] = args;
      if (!url) {
        throw new FriendlyError('Missing required argument <url>. Try: browser open "https://example.com"');
      }
      const wait = typeof options.wait === "string" ? options.wait : undefined;
      return commandBridge.call("open", {
        url,
        wait,
        newTab: Boolean(options.new || options.window),
        newWindow: Boolean(options.window),
        noDelay: Boolean(options.noDelay),
        ...buildTabParams(options),
      });
    }

    case "tabs": {
      return commandBridge.call("tabs", {});
    }

    case "focus": {
      if (!args[0]) {
        throw new FriendlyError('Missing required argument <alias>. Try: browser focus t0');
      }
      return commandBridge.call("focus", { alias: args[0] });
    }

    case "close": {
      if (!args[0]) {
        throw new FriendlyError('Missing required argument <alias>. Try: browser close t0');
      }
      return commandBridge.call("close", { alias: args[0] });
    }

    case "close-idle": {
      const hours = parseNumberOption(options.hours, 0);
      if (hours <= 0) {
        throw new FriendlyError("--hours must be greater than zero.");
      }
      return commandBridge.call("close-idle", { hours, dryRun: Boolean(options.dryRun) }, CLOSE_IDLE_TIMEOUT_MS);
    }

    case "click": {
      const [target] = args;
      if (!target) {
        throw new FriendlyError('Missing required argument <target>. Try: browser click "More"');
      }
      const index = parseNumberOption(options.index, 0);
      return commandBridge.call("click", {
        target,
        index,
        text: Boolean(options.text),
        coords: Boolean(options.coords),
        noDelay: Boolean(options.noDelay),
        ...buildTabParams(options),
      });
    }

    case "type": {
      const [target, text] = args;
      if (!target || typeof text !== "string") {
        throw new FriendlyError('Missing required arguments <target> <text>. Try: browser type "Search" "browser CLI"');
      }
      const index = parseNumberOption(options.index, 0);
      return commandBridge.call("type", { target, text, index, noDelay: Boolean(options.noDelay), ...buildTabParams(options) });
    }

    case "fill": {
      const [target, text = ""] = args;
      if (!target) {
        throw new FriendlyError('Missing required argument <target>. Try: browser fill "Description" "New text"');
      }
      const clear = Boolean(options.clear);
      if (!clear && typeof text !== "string") {
        throw new FriendlyError('Missing required argument <text>. Try: browser fill "Description" "New text"');
      }
      const index = parseNumberOption(options.index, 0);
      return commandBridge.call("fill", {
        target,
        text,
        index,
        clear,
        append: Boolean(options.append),
        noDelay: Boolean(options.noDelay),
        ...buildTabParams(options),
      });
    }

    case "upload": {
      const [target, requestedPath] = args;
      if (!target || !requestedPath) {
        throw new FriendlyError('Missing required arguments <target> <filepath>. Try: browser upload "input[type=file]" /path/to/file');
      }

      const resolvedPath = path.resolve(requestedPath);
      try {
        await fs.access(resolvedPath);
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        throw new FriendlyError(`File does not exist or is not readable: ${resolvedPath} (${message})`);
      }

      return commandBridge.call("upload", { target, filepath: resolvedPath, noDelay: Boolean(options.noDelay), ...buildTabParams(options) });
    }

    case "wait": {
      const [selector] = args;
      const timeout = parseNumberOption(options.timeout, 15_000);
      const delayMaximum =
        typeof options.ms === "string"
          ? Number(options.ms.includes("-") ? options.ms.split("-")[1] : options.ms)
          : 0;
      const bridgeTimeout = Math.max(timeout, delayMaximum) + BRIDGE_TIMEOUT_GRACE_MS;
      return commandBridge.call("wait", {
        selector: selector ?? null,
        text: typeof options.text === "string" ? options.text : null,
        gone: typeof options.gone === "string" ? options.gone : null,
        stable: typeof options.stable === "string" ? options.stable : null,
        ms: typeof options.ms === "string" ? options.ms : null,
        timeout,
        ...buildTabParams(options),
      }, bridgeTimeout);
    }

    case "snapshot": {
      return commandBridge.call("snapshot", {
        scope: typeof options.scope === "string" ? options.scope : null,
        depth: parseNumberOption(options.depth, -1),
        ...buildTabParams(options),
      });
    }

    case "diff": {
      return commandBridge.call("diff", {
        scope: typeof options.scope === "string" ? options.scope : null,
        depth: parseNumberOption(options.depth, -1),
        ...buildTabParams(options),
      });
    }

    case "inspect": {
      return commandBridge.call("inspect", {
        scope: typeof options.scope === "string" ? options.scope : null,
        all: Boolean(options.all),
        coords: Boolean(options.coords),
        ...buildTabParams(options),
      });
    }

    case "describe": {
      return oracleRunner({
        prompt: DESCRIBE_SYSTEM_PROMPT,
        scope: typeof options.scope === "string" ? options.scope : undefined,
        model: typeof options.model === "string" ? options.model : undefined,
        tabId: typeof options.tab === "string" ? options.tab : undefined,
      }, commandBridge);
    }

    case "ask": {
      const [question] = args;
      if (!question) {
        throw new FriendlyError('Missing required argument <question>. Try: browser ask "what error message is showing?"');
      }
      return oracleRunner({
        prompt: ASK_SYSTEM_PROMPT,
        question,
        scope: typeof options.scope === "string" ? options.scope : undefined,
        model: typeof options.model === "string" ? options.model : undefined,
        tabId: typeof options.tab === "string" ? options.tab : undefined,
      }, commandBridge);
    }

    case "extract": {
      const [selector] = args;
      return commandBridge.call("extract", {
        selector: selector ?? null,
        scope: typeof options.scope === "string" ? options.scope : null,
        json: Boolean(options.json),
        limit: parseNumberOption(options.limit, DEFAULT_EXTRACT_LIMIT),
        ...buildTabParams(options),
      });
    }

    case "screenshot": {
      const [requestedPath] = args;
      const targetPath = requestedPath ? path.resolve(requestedPath) : path.resolve(process.cwd(), "screenshot.png");
      if (!targetPath.endsWith(".png")) {
        throw new FriendlyError(`Screenshot path must end with .png. Try: browser screenshot ${targetPath}.png`);
      }

      const result = await commandBridge.call("screenshot", buildTabParams(options));
      if (!isObject(result) || typeof result.dataUrl !== "string") {
        throw new FriendlyError("Extension did not return screenshot data.");
      }

      const base64 = result.dataUrl.replace(/^data:image\/png;base64,/, "");
      await fs.mkdir(path.dirname(targetPath), { recursive: true });
      await fs.writeFile(targetPath, Buffer.from(base64, "base64"));
      const mode = parseString(result.mode, "viewport");
      const warning = parseString(result.warning);
      const warningSuffix = warning ? ` (${warning})` : "";
      return `Saved ${mode} screenshot to ${targetPath}${warningSuffix}`;
    }

    case "html": {
      const [selector] = args;
      return commandBridge.call("html", {
        selector: selector ?? null,
        limit: parseNumberOption(options.limit, DEFAULT_HTML_LIMIT),
        ...buildTabParams(options),
      });
    }

    case "eval": {
      const expression = args.join(" ").trim();
      if (!expression) {
        throw new FriendlyError('Missing required argument <js>. Try: browser eval "document.title"');
      }
      return commandBridge.call("eval", { expression, ...buildTabParams(options) });
    }

    case "dialog": {
      return commandBridge.call("dialog", {
        accept: options.accept,
        dismiss: Boolean(options.dismiss),
        ...buildTabParams(options),
      });
    }

    case "status": {
      try {
        const status = await commandBridge.call("status", buildTabParams(options));
        if (isObject(status)) {
          return {
            ...status,
            uptimeMs: Date.now() - state.startedAt,
            extensionConnected: commandBridge.getStatus().connected,
          };
        }
      } catch (error) {
        if (typeof options.tab === "string" && options.tab.trim()) {
          throw error;
        }
        return {
          message:
            error instanceof Error
              ? error.message
              : "Chrome extension bridge is disconnected. Load the extension from src/browser/extension.",
          url: "about:blank",
          title: "",
          uptimeMs: Date.now() - state.startedAt,
          extensionConnected: commandBridge.getStatus().connected,
        };
      }
      return {
        url: "about:blank",
        title: "",
        uptimeMs: Date.now() - state.startedAt,
        extensionConnected: commandBridge.getStatus().connected,
      };
    }

    case "stop": {
      const location = await getCurrentLocation(commandBridge);
      return {
        message: "Browser server stopping.",
        ...location,
        uptimeMs: Date.now() - state.startedAt,
        extensionConnected: commandBridge.getStatus().connected,
        shouldStop: true,
      };
    }

    default:
      throw new FriendlyError("Unknown command. Try: browser help");
  }
}

export type CommandExecutor = (body: CommandRequest, signal?: AbortSignal) => Promise<CommandResponse>;

async function executeCommand(body: CommandRequest, signal?: AbortSignal): Promise<CommandResponse> {
  const started = Date.now();
  const commandBridge = requireBridge();
  const scopedBridge: CommandBridge = {
    getStatus: () => commandBridge.getStatus(),
    call: (action, params, timeoutMs) => commandBridge.call(action, params, timeoutMs, signal),
  };

  try {
    const data = await runCommand(body, scopedBridge);
    const shouldStop = isObject(data) && Boolean(data.shouldStop);
    const responseData =
      shouldStop && isObject(data) ? Object.fromEntries(Object.entries(data).filter(([key]) => key !== "shouldStop")) : data;

    const location = extractLocation(responseData) ?? (signal?.aborted ? { url: "about:blank", title: "" } : await getCurrentLocation(commandBridge));
    const response: CommandResponse = {
      ok: true,
      data: responseData,
      url: location.url,
      title: location.title,
      elapsed: Date.now() - started,
    };

    if (shouldStop) {
      setTimeout(() => {
        void shutdown().finally(() => process.exit(0));
      }, 50);
    }

    return response;
  } catch (error) {
    const location = signal?.aborted ? { url: "about:blank", title: "" } : await getCurrentLocation(commandBridge);
    return {
      ok: false,
      error: error instanceof Error ? error.message : String(error),
      url: location.url,
      title: location.title,
      elapsed: Date.now() - started,
    };
  }
}

function writeJson(response: http.ServerResponse, statusCode: number, body: unknown) {
  response.writeHead(statusCode, { "content-type": "application/json; charset=utf-8" });
  response.end(JSON.stringify(body));
}

function writeCommandError(response: http.ServerResponse, statusCode: number, error: string) {
  writeJson(response, statusCode, {
    ok: false,
    error,
    url: "about:blank",
    title: "",
    elapsed: 0,
  } satisfies CommandResponse);
}

async function requestHandler(
  request: http.IncomingMessage,
  response: http.ServerResponse,
  commandExecutor: CommandExecutor,
) {
  if (request.method === "GET" && request.url === "/health") {
    writeJson(response, 200, {
      service: "browser-cli",
      ok: bridge !== null,
      uptimeMs: Date.now() - state.startedAt,
      extensionConnected: bridge?.getStatus().connected ?? false,
    });
    return;
  }

  if (request.method === "POST" && request.url === "/command") {
    // This endpoint may be reachable over loopback when Unix sockets are not
    // available. Reject browser-origin and simple/no-CORS requests before
    // consuming their bodies; CORS response headers are not a security check.
    if (request.headers.origin !== undefined) {
      writeCommandError(response, 403, "Browser-origin command requests are forbidden.");
      return;
    }

    const contentType = request.headers["content-type"];
    const mediaType = typeof contentType === "string" ? contentType.split(";", 1)[0]?.trim().toLowerCase() : "";
    if (mediaType !== "application/json") {
      writeCommandError(response, 415, "Command requests require Content-Type: application/json.");
      return;
    }

    const cancellation = new AbortController();
    request.once("aborted", () => cancellation.abort());
    response.once("close", () => {
      if (!response.writableEnded) cancellation.abort();
    });
    try {
      const body = (await parseJsonBody(request)) as CommandRequest;
      if (!body?.command || !COMMAND_NAMES.has(body.command)) {
        throw new FriendlyError("Invalid command payload. Try: browser help");
      }
      const result = await commandExecutor(body, cancellation.signal);
      writeJson(response, 200, result);
      return;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      writeCommandError(response, 400, message);
      return;
    }
  }

  writeJson(response, 404, { ok: false, error: "Not found" });
}

export function createRequestHandler(commandExecutor: CommandExecutor = executeCommand): http.RequestListener {
  return (request, response) => {
    void requestHandler(request, response, commandExecutor);
  };
}

export async function startServer(): Promise<boolean> {
  if (server || bridge) {
    throw new Error("Browser server is already running in this process.");
  }

  const candidateServer = http.createServer(createRequestHandler());
  const listener = await listenForCommands(candidateServer, {
    socketPath: SOCKET_PATH,
    fallbackPort: FALLBACK_PORT,
  });
  if (listener.transport === "existing") {
    return false;
  }

  server = candidateServer;
  ownsSocket = listener.ownsSocket;
  if (ownsSocket) {
    await fs.chmod(SOCKET_PATH, 0o600).catch(() => undefined);
  }

  const candidateBridge = new ExtensionBridge();
  try {
    await candidateBridge.ready();
    bridge = candidateBridge;
  } catch (error) {
    await candidateBridge.close().catch(() => undefined);
    await new Promise<void>((resolve) => candidateServer.close(() => resolve()));
    server = null;
    if (ownsSocket) {
      await fs.rm(SOCKET_PATH, { force: true }).catch(() => undefined);
      ownsSocket = false;
    }
    const message = error instanceof Error ? error.message : String(error);
    throw new FriendlyError(`Cannot start extension bridge on 127.0.0.1:${BRIDGE_WS_PORT}: ${message}`);
  }
  return true;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  void startServer().catch((error) => {
    process.stderr.write(`[browser-server] ${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  });
  process.on("SIGINT", () => {
    void shutdown().finally(() => process.exit(0));
  });
  process.on("SIGTERM", () => {
    void shutdown().finally(() => process.exit(0));
  });
}
