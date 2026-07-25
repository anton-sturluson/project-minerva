import { spawn } from "node:child_process";
import http from "node:http";
import path from "node:path";
import process from "node:process";
import { fileURLToPath, pathToFileURL } from "node:url";
import { formatError, formatMetadata, formatSuccess } from "./lib/format.js";
import { parseCliInput } from "./lib/parse.js";
import { FALLBACK_PORT, SOCKET_PATH } from "./lib/types.js";
import type { CommandRequest, CommandResponse } from "./lib/types.js";

const HEALTH_REQUEST_TIMEOUT_MS = 2_000;
const COMMAND_REQUEST_TIMEOUT_MS = 150_000;

function requestTimeoutForPath(requestPath: string, body?: unknown): number {
  if (requestPath === "/health") return HEALTH_REQUEST_TIMEOUT_MS;
  if (
    typeof body === "object" && body !== null &&
    (body as { command?: unknown }).command === "wait"
  ) {
    const options = (body as { options?: Record<string, unknown> }).options ?? {};
    const timeout = typeof options.timeout === "number" ? options.timeout : 15_000;
    const ms = typeof options.ms === "string"
      ? Number(options.ms.includes("-") ? options.ms.split("-")[1] : options.ms)
      : 0;
    const requested = Math.max(timeout, Number.isFinite(ms) ? ms : 0) + 15_000;
    return Math.min(2_147_000_000, Math.max(COMMAND_REQUEST_TIMEOUT_MS, requested));
  }
  return COMMAND_REQUEST_TIMEOUT_MS;
}

function canTryFallback(error: unknown): boolean {
  const code = (error as NodeJS.ErrnoException)?.code;
  return code === "ENOENT" || code === "ECONNREFUSED" || code === "EACCES" || code === "ENOTSOCK";
}

function outputAndExit(ok: boolean, text: string, code = ok ? 0 : 1): never {
  const body = `${text}\n${formatMetadata(ok, "unavailable", 0)}`;
  process.stdout.write(`${body}\n`);
  process.exit(code);
}

function sendRequestViaSocket<T>(method: string, requestPath: string, body?: unknown): Promise<T> {
  return new Promise((resolve, reject) => {
    const request = http.request(
      {
        method,
        socketPath: SOCKET_PATH,
        path: requestPath,
        headers: body ? { "content-type": "application/json" } : undefined,
      },
      (response) => {
        const chunks: Buffer[] = [];
        response.on("data", (chunk) => chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk)));
        response.on("end", () => {
          const payload = Buffer.concat(chunks).toString("utf8");
          try {
            resolve(JSON.parse(payload) as T);
          } catch (error) {
            reject(error);
          }
        });
      },
    );

    request.setTimeout(requestTimeoutForPath(requestPath, body), () => {
      request.destroy(new Error(`Browser server request timed out (${requestPath}).`));
    });
    request.on("error", reject);
    if (body) {
      request.write(JSON.stringify(body));
    }
    request.end();
  });
}

function sendRequestViaPort<T>(method: string, requestPath: string, body?: unknown): Promise<T> {
  return new Promise((resolve, reject) => {
    const request = http.request(
      {
        method,
        host: "127.0.0.1",
        port: FALLBACK_PORT,
        path: requestPath,
        headers: body ? { "content-type": "application/json" } : undefined,
      },
      (response) => {
        const chunks: Buffer[] = [];
        response.on("data", (chunk) => chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk)));
        response.on("end", () => {
          const payload = Buffer.concat(chunks).toString("utf8");
          try {
            resolve(JSON.parse(payload) as T);
          } catch (error) {
            reject(error);
          }
        });
      },
    );

    request.setTimeout(requestTimeoutForPath(requestPath, body), () => {
      request.destroy(new Error(`Browser server request timed out (${requestPath}).`));
    });
    request.on("error", reject);
    if (body) {
      request.write(JSON.stringify(body));
    }
    request.end();
  });
}

async function sendRequest<T>(method: string, requestPath: string, body?: unknown): Promise<T> {
  try {
    return await sendRequestViaSocket<T>(method, requestPath, body);
  } catch (error) {
    if (!canTryFallback(error)) throw error;
    return sendRequestViaPort<T>(method, requestPath, body);
  }
}

function spawnServer() {
  const modulePath = fileURLToPath(import.meta.url);
  const moduleDir = path.dirname(modulePath);
  const packageRoot = path.resolve(moduleDir, "..");
  const distServer = path.resolve(packageRoot, "dist/server.js");
  const srcServer = path.resolve(packageRoot, "src/server.ts");

  if (modulePath.includes(`${path.sep}dist${path.sep}`)) {
    const child = spawn(process.execPath, [distServer], {
      cwd: packageRoot,
      detached: true,
      stdio: "ignore",
    });
    child.unref();
    return;
  }

  const child = spawn("npx", ["tsx", srcServer], {
    cwd: packageRoot,
    detached: true,
    stdio: "ignore",
  });
  child.unref();
}

async function serverIsReady(): Promise<boolean> {
  const health = await sendRequest<{ ok?: unknown }>("GET", "/health");
  return health.ok === true;
}

async function ensureServer() {
  try {
    if (await serverIsReady()) return;
  } catch {
    spawnServer();
  }

  const deadline = Date.now() + 10_000;
  while (Date.now() < deadline) {
    try {
      if (await serverIsReady()) return;
    } catch {
      await new Promise((resolve) => setTimeout(resolve, 200));
    }
  }

  outputAndExit(
    false,
    "[error] Server did not start within 10s. Try: npm run build (in src/browser) and then browser open <url>",
  );
}

export async function main(argv = process.argv.slice(2)): Promise<never> {
  const parsed = parseCliInput(argv);
  if (parsed.localOutput) {
    outputAndExit(parsed.localOutput.ok, parsed.localOutput.text, parsed.localOutput.ok ? 0 : 1);
  }

  if (!parsed.command) {
    outputAndExit(false, "[error] No command provided. Try: browser help");
  }

  const request: CommandRequest = {
    command: parsed.command,
    args: parsed.args,
    options: parsed.options,
  };

  try {
    if (parsed.allowAutoStart) {
      await ensureServer();
    }

    const response = await sendRequest<CommandResponse>("POST", "/command", request);
    const text = response.ok
      ? formatSuccess(parsed.command, response.data, response.url, response.elapsed)
      : formatError(response.error ?? "Unknown error", response.url, response.elapsed);
    process.stdout.write(`${text}\n`);
    process.exit(response.ok ? 0 : 1);
  } catch {
    const help =
      parsed.command === "stop"
        ? "Server not running. It will auto-start on next command, or run: browser open <url>"
        : "Unable to reach browser server. It will auto-start on next command, or run: browser open <url>";
    process.stdout.write(`${formatError(help, "unavailable", 0)}\n`);
    process.exit(1);
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  void main();
}
