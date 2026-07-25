import { OUTPUT_LINE_LIMIT } from "./types.js";
import type { CommandName } from "./types.js";

function truncateLines(text: string, maxLines = OUTPUT_LINE_LIMIT): string {
  const lines = text.split("\n");
  if (lines.length <= maxLines) {
    return text;
  }

  const preview = lines.slice(0, maxLines).join("\n");
  return `${preview}\n[truncated: showing ${maxLines}/${lines.length} lines. Use command-specific --limit or --scope options when available]`;
}

function stringifyData(data: unknown): string {
  if (data == null) {
    return "";
  }
  if (typeof data === "string") {
    return data;
  }
  return JSON.stringify(data, null, 2);
}

function formatUptime(uptimeMs: number): string {
  if (uptimeMs < 1_000) {
    return `${uptimeMs}ms`;
  }
  if (uptimeMs < 60_000) {
    return `${(uptimeMs / 1_000).toFixed(1)}s`;
  }
  return `${(uptimeMs / 60_000).toFixed(1)}m`;
}

function renderStateChanges(data: Record<string, unknown>): string {
  const changes = data.stateChanges;
  if (!Array.isArray(changes) || changes.length === 0) {
    return "";
  }
  return `State changes:\n${changes.map((c) => `  ${String(c)}`).join("\n")}`;
}

function renderTabsTable(data: unknown): string {
  if (!Array.isArray(data) || data.length === 0) {
    return "No managed tabs.";
  }

  return data
    .map((item) => {
      const record = item as { alias?: unknown; url?: unknown; title?: unknown; active?: unknown };
      const marker = record.active ? "*" : " ";
      const alias = String(record.alias ?? "?").padEnd(3);
      const url = String(record.url ?? "about:blank").padEnd(32);
      return `${marker} ${alias} ${url} "${String(record.title ?? "")}"`;
    })
    .join("\n");
}

function renderCommandData(command: CommandName, data: unknown): string {
  if (command === "open" && typeof data === "object" && data !== null) {
    const record = data as { title?: unknown; preview?: unknown };
    return `Title: ${String(record.title ?? "(untitled)")}\nPreview: ${String(record.preview ?? "[blank]")}`;
  }

  if (command === "tabs") {
    return renderTabsTable(data);
  }

  if ((command === "focus" || command === "close") && typeof data === "object" && data !== null) {
    const record = data as { alias?: unknown; tabId?: unknown; url?: unknown; title?: unknown; active?: unknown };
    const lines = [
      `${command === "focus" ? "Focused" : "Closed"}: ${String(record.alias ?? record.tabId ?? "")}`,
      `Tab id: ${String(record.tabId ?? "")}`,
      `URL: ${String(record.url ?? "about:blank")}`,
    ];
    if (record.title) {
      lines.push(`Title: ${String(record.title)}`);
    }
    if (command === "focus" && typeof record.active === "boolean") {
      lines.push(`Active: ${record.active ? "yes" : "no"}`);
    }
    return lines.join("\n");
  }

  if (command === "close-idle" && typeof data === "object" && data !== null) {
    const record = data as Record<string, unknown>;
    const eligible = Array.isArray(record.eligible) ? record.eligible : [];
    const closed = Array.isArray(record.closed) ? record.closed : [];
    const skipped = Array.isArray(record.skipped) ? record.skipped : [];
    const failed = Array.isArray(record.failed) ? record.failed : [];
    const eligibleCount = Number(record.eligibleCount ?? eligible.length);
    const closedCount = Number(record.closedCount ?? closed.length);
    const skippedCount = Number(record.skippedCount ?? skipped.length);
    const failedCount = Number(record.failedCount ?? failed.length);
    const dryRun = Boolean(record.dryRun);
    const lines = [
      `Eligible: ${eligibleCount} tab(s) idle for at least ${String(record.hours ?? "?")} hour(s).`,
      dryRun ? "Dry run: no tabs were closed." : `Closed: ${closedCount} tab(s).`,
      `Skipped: ${skippedCount} tab(s).`,
      `Failed: ${failedCount} tab(s).`,
    ];

    const displayed = dryRun ? eligible : closed;
    if (displayed.length > 0) {
      lines.push(dryRun ? "Eligible tabs:" : "Closed tabs:");
      for (const item of displayed) {
        const tab = item as Record<string, unknown>;
        lines.push(`- ${String(tab.idleHours ?? "?")}h — ${String(tab.title ?? "(untitled)")} — ${String(tab.url ?? "about:blank")}`);
      }
    }

    if (skipped.length > 0) {
      const reasonCounts = new Map<string, number>();
      for (const item of skipped) {
        const reason = String((item as Record<string, unknown>).reason ?? "unknown");
        reasonCounts.set(reason, (reasonCounts.get(reason) ?? 0) + 1);
      }
      lines.push(`Skip reasons: ${Array.from(reasonCounts, ([reason, count]) => `${reason}=${count}`).join(", ")}`);
    }

    for (const item of failed) {
      const tab = item as Record<string, unknown>;
      lines.push(`Failure (${String(tab.stage ?? "unknown")}): ${String(tab.title ?? tab.url ?? tab.id ?? "tab")} — ${String(tab.error ?? "unknown error")}`);
    }
    return lines.join("\n");
  }

  if (command === "click" && typeof data === "object" && data !== null) {
    const record = data as Record<string, unknown>;
    const lines = [
      `Clicked: ${String(record.clicked ?? "")}`,
      `Resolved: ${String(record.target ?? "")}`,
    ];
    if (record.coords) {
      lines.push(`Coords: ${JSON.stringify(record.coords)}`);
    }
    const sc = renderStateChanges(record);
    if (sc) lines.push(sc);
    lines.push(`Title: ${String(record.title ?? "(untitled)")}`);
    lines.push(`Preview: ${String(record.preview ?? "[blank]")}`);
    return lines.join("\n").trim();
  }

  if (command === "type" && typeof data === "object" && data !== null) {
    const record = data as Record<string, unknown>;
    const lines = [
      `Filled: ${String(record.typedInto ?? "")}`,
      `Resolved: ${String(record.target ?? "")}`,
      `Text: ${String(record.text ?? "")}`,
    ];
    const sc = renderStateChanges(record);
    if (sc) lines.push(sc);
    return lines.join("\n").trim();
  }

  if (command === "fill" && typeof data === "object" && data !== null) {
    const record = data as Record<string, unknown>;
    const lines = [
      `Filled: ${String(record.filledInto ?? "")}`,
      `Resolved: ${String(record.target ?? "")}`,
      `Intended: ${String(record.intended ?? "")}`,
      `Actual: ${String(record.actual ?? "")}`,
      `Match: ${String(record.match ?? false)}`,
    ];
    const sc = renderStateChanges(record);
    if (sc) lines.push(sc);
    return lines.join("\n").trim();
  }

  if (command === "upload" && typeof data === "object" && data !== null) {
    const record = data as Record<string, unknown>;
    const lines = [
      `Uploaded: ${String(record.uploaded ?? "")}`,
      `Target: ${String(record.target ?? "")}`,
      `Resolved: ${String(record.selector ?? "")}`,
    ];
    const sc = renderStateChanges(record);
    if (sc) lines.push(sc);
    lines.push(`Title: ${String(record.title ?? "(untitled)")}`);
    lines.push(`Preview: ${String(record.preview ?? "[blank]")}`);
    return lines.join("\n").trim();
  }

  if (command === "wait" && typeof data === "object" && data !== null) {
    const record = data as { condition?: unknown; waitedFor?: unknown; waitedMs?: unknown; title?: unknown; preview?: unknown };
    const lines = [`Condition: ${String(record.condition ?? "")}`];
    if (record.waitedFor != null) {
      lines.push(`Waited for: ${String(record.waitedFor)}`);
    }
    if (record.waitedMs != null) {
      lines.push(`Waited ms: ${String(record.waitedMs)}`);
    }
    if (record.title != null) {
      lines.push(`Title: ${String(record.title)}`);
    }
    if (record.preview != null) {
      lines.push(`Preview: ${String(record.preview)}`);
    }
    return lines.join("\n");
  }

  if ((command === "snapshot" || command === "diff") && typeof data === "object" && data !== null) {
    const record = data as { snapshot?: unknown; diff?: unknown };
    const text = typeof record.snapshot === "string" ? record.snapshot : typeof record.diff === "string" ? record.diff : "";
    return text || stringifyData(data);
  }

  if (command === "describe" || command === "ask") {
    return stringifyData(data);
  }

  if (command === "dialog" && typeof data === "object" && data !== null) {
    const record = data as { open?: unknown; handled?: unknown; type?: unknown; message?: unknown; defaultPrompt?: unknown };
    const lines: string[] = [];
    if (record.handled) {
      lines.push(`Handled: ${String(record.handled)}`);
    } else {
      lines.push(`Open: ${String(record.open ?? false)}`);
    }
    if (record.type) {
      lines.push(`Type: ${String(record.type)}`);
    }
    if (record.message) {
      lines.push(`Message: ${String(record.message)}`);
    }
    if (record.defaultPrompt) {
      lines.push(`Default prompt: ${String(record.defaultPrompt)}`);
    }
    return lines.join("\n");
  }

  if ((command === "status" || command === "stop") && typeof data === "object" && data !== null) {
    const record = data as {
      message?: unknown;
      url?: unknown;
      title?: unknown;
      uptimeMs?: unknown;
      extensionConnected?: unknown;
      managedTabId?: unknown;
      managedAlias?: unknown;
      managedWindowId?: unknown;
      activeTabId?: unknown;
      activeManagedTabId?: unknown;
      activeManagedAlias?: unknown;
      managedTabs?: unknown;
      usingManagedTab?: unknown;
    };
    const lines: string[] = [];
    if (record.message) {
      lines.push(String(record.message));
    }
    lines.push(`URL: ${String(record.url ?? "about:blank")}`);
    if (record.title) {
      lines.push(`Title: ${String(record.title)}`);
    }
    if (typeof record.uptimeMs === "number") {
      lines.push(`Uptime: ${formatUptime(record.uptimeMs)}`);
    }
    if (record.managedTabId != null) {
      lines.push(`Managed tab id: ${String(record.managedTabId)}`);
    }
    if (record.managedAlias != null) {
      lines.push(`Managed alias: ${String(record.managedAlias)}`);
    }
    if (record.managedWindowId != null) {
      lines.push(`Managed window id: ${String(record.managedWindowId)}`);
    }
    if (record.activeTabId != null) {
      lines.push(`Active tab id: ${String(record.activeTabId)}`);
    }
    if (record.activeManagedTabId != null) {
      lines.push(`Active managed tab id: ${String(record.activeManagedTabId)}`);
    }
    if (record.activeManagedAlias != null) {
      lines.push(`Active managed alias: ${String(record.activeManagedAlias)}`);
    }
    if (typeof record.usingManagedTab === "boolean") {
      lines.push(`Using managed tab: ${record.usingManagedTab ? "yes" : "no"}`);
    }
    if (typeof record.extensionConnected === "boolean") {
      lines.push(`Extension: ${record.extensionConnected ? "connected" : "disconnected"}`);
    }
    if (Array.isArray(record.managedTabs) && record.managedTabs.length > 0) {
      lines.push("Tabs:");
      lines.push(renderTabsTable(record.managedTabs));
    }
    return lines.join("\n");
  }

  return stringifyData(data);
}

export function formatMetadata(ok: boolean, url: string, elapsed: number): string {
  return `[${ok ? "ok" : "error"} | url: ${url || "about:blank"} | ${Math.max(0, Math.round(elapsed))}ms]`;
}

export function formatSuccess(command: CommandName, data: unknown, url: string, elapsed: number): string {
  const body = truncateLines(renderCommandData(command, data).trim());
  if (!body) {
    return formatMetadata(true, url, elapsed);
  }
  return `${body}\n${formatMetadata(true, url, elapsed)}`;
}

export function formatError(message: string, url: string, elapsed: number): string {
  const body = truncateLines(`[error] ${message}`.trim());
  return `${body}\n${formatMetadata(false, url || "unavailable", elapsed)}`;
}
