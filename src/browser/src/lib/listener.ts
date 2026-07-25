import fs from "node:fs/promises";
import http from "node:http";
import process from "node:process";

export type ListenTransport = "socket" | "port" | "existing";
export interface ListenResult {
  transport: ListenTransport;
  ownsSocket: boolean;
}

interface ListenOptions {
  socketPath: string;
  fallbackPort: number;
  host?: string;
  startupTimeoutMs?: number;
  probeTimeoutMs?: number;
}

type ProbeResult = "browser" | "stale" | "occupied";

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function attemptListen(server: http.Server, target: string | { port: number; host: string }): Promise<void> {
  return new Promise((resolve, reject) => {
    const onListening = () => {
      cleanup();
      resolve();
    };
    const onError = (error: Error) => {
      cleanup();
      reject(error);
    };
    const cleanup = () => {
      server.off("listening", onListening);
      server.off("error", onError);
    };
    server.once("listening", onListening);
    server.once("error", onError);
    if (typeof target === "string") server.listen(target);
    else server.listen(target.port, target.host);
  });
}

async function probeHealth(
  target: { socketPath: string } | { host: string; port: number },
  timeoutMs: number,
): Promise<ProbeResult> {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (result: ProbeResult) => {
      if (settled) return;
      settled = true;
      resolve(result);
    };
    const request = http.request({ ...target, method: "GET", path: "/health" }, (response) => {
      const chunks: Buffer[] = [];
      response.on("data", (chunk) => chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk)));
      response.on("end", () => {
        try {
          const payload = JSON.parse(Buffer.concat(chunks).toString("utf8")) as { ok?: unknown; service?: unknown };
          finish(response.statusCode === 200 && payload.service === "browser-cli" ? "browser" : "occupied");
        } catch {
          finish("occupied");
        }
      });
    });
    request.setTimeout(timeoutMs, () => {
      request.destroy();
      finish("occupied");
    });
    request.on("error", (error: NodeJS.ErrnoException) => {
      finish(error.code === "ENOENT" || error.code === "ECONNREFUSED" ? "stale" : "occupied");
    });
    request.end();
  });
}

async function processIsAlive(pid: number): Promise<boolean> {
  if (!Number.isSafeInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return (error as NodeJS.ErrnoException).code === "EPERM";
  }
}

async function acquireLock(lockPath: string): Promise<null | (() => Promise<void>)> {
  try {
    const handle = await fs.open(lockPath, "wx", 0o600);
    await handle.writeFile(`${process.pid}\n`);
    await handle.close();
    return async () => fs.rm(lockPath, { force: true }).catch(() => undefined);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
  }

  try {
    const stat = await fs.lstat(lockPath);
    if (typeof process.getuid === "function" && stat.uid !== process.getuid()) {
      throw new Error(`Startup lock is owned by another user: ${lockPath}`);
    }
    const raw = await fs.readFile(lockPath, "utf8");
    const pid = Number.parseInt(raw.trim(), 10);
    if (await processIsAlive(pid)) return null;
    // Invalid, freshly-created contents may just be between open() and write().
    if (!Number.isSafeInteger(pid) && Date.now() - stat.mtimeMs < 10_000) return null;
    await fs.rm(lockPath, { force: true });
    return acquireLock(lockPath);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw error;
  }
}

async function removeStaleSocket(socketPath: string): Promise<void> {
  try {
    const stat = await fs.lstat(socketPath);
    if (!stat.isSocket()) {
      throw new Error(`Refusing to remove non-socket path: ${socketPath}`);
    }
    if (typeof process.getuid === "function" && stat.uid !== process.getuid()) {
      throw new Error(`Refusing to remove socket owned by another user: ${socketPath}`);
    }
    await fs.unlink(socketPath);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
  }
}

export async function listenForCommands(server: http.Server, options: ListenOptions): Promise<ListenResult> {
  const host = options.host ?? "127.0.0.1";
  const timeoutMs = options.startupTimeoutMs ?? 10_000;
  const probeTimeoutMs = options.probeTimeoutMs ?? 500;
  const lockPath = `${options.socketPath}.startup.lock`;
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    // A lock closes the unlink-to-bind race: non-winners wait rather than bind
    // the just-unlinked path before the lock holder can do so.
    const lockExists = await fs.access(lockPath).then(() => true, () => false);
    if (lockExists) {
      const release = await acquireLock(lockPath);
      if (!release) {
        await delay(20);
        continue;
      }
      await release();
    }

    try {
      await attemptListen(server, options.socketPath);
      return { transport: "socket", ownsSocket: true };
    } catch (error) {
      const code = (error as NodeJS.ErrnoException).code;
      if (code === "EACCES" || code === "EPERM") break;
      if (code !== "EADDRINUSE") throw error;
    }

    const probe = await probeHealth({ socketPath: options.socketPath }, probeTimeoutMs);
    if (probe === "browser") return { transport: "existing", ownsSocket: false };
    if (probe === "occupied") throw new Error(`Command socket is occupied by another live service: ${options.socketPath}`);

    const release = await acquireLock(lockPath);
    if (!release) {
      await delay(20);
      continue;
    }
    try {
      const recheck = await probeHealth({ socketPath: options.socketPath }, probeTimeoutMs);
      if (recheck === "browser") return { transport: "existing", ownsSocket: false };
      if (recheck === "occupied") throw new Error(`Command socket is occupied by another live service: ${options.socketPath}`);
      await removeStaleSocket(options.socketPath);
      try {
        await attemptListen(server, options.socketPath);
        return { transport: "socket", ownsSocket: true };
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== "EADDRINUSE") throw error;
      }
    } finally {
      await release();
    }
  }

  try {
    await attemptListen(server, { host, port: options.fallbackPort });
    return { transport: "port", ownsSocket: false };
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "EADDRINUSE") throw error;
    const probe = await probeHealth({ host, port: options.fallbackPort }, probeTimeoutMs);
    if (probe === "browser") return { transport: "existing", ownsSocket: false };
    throw new Error(`Fallback command port ${options.fallbackPort} is unavailable.`);
  }
}
