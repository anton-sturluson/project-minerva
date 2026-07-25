const HOUR_MS = 60 * 60 * 1000;

export function assertValidIdleHours(hours) {
  if (!Number.isSafeInteger(hours) || hours <= 0) {
    throw new Error("hours must be a positive safe integer.");
  }
}

function tabDetails(tab, now) {
  const lastAccessed = Number.isFinite(tab?.lastAccessed) ? tab.lastAccessed : null;
  return {
    id: tab?.id,
    windowId: Number.isInteger(tab?.windowId) ? tab.windowId : null,
    url: tab?.url || "about:blank",
    title: tab?.title || "",
    lastAccessed,
    idleHours: lastAccessed == null ? null : Number(((now - lastAccessed) / HOUR_MS).toFixed(1)),
  };
}

function skipReason(tab, window, cutoff) {
  if (!Number.isInteger(tab?.id)) {
    return "invalid-tab-id";
  }
  if (window?.type !== "normal") {
    return "non-normal-window";
  }
  if (tab.pinned) {
    return "pinned";
  }
  if (tab.audible) {
    return "audible";
  }
  // Every window has an active tab. This intentionally protects active tabs in
  // background windows as well as the last-focused window.
  if (tab.active) {
    return "active";
  }
  if (!Number.isFinite(tab.lastAccessed) || tab.lastAccessed <= 0) {
    return "missing-last-accessed";
  }
  if (tab.lastAccessed > cutoff) {
    return "not-idle";
  }
  return null;
}

function isVanishedError(error) {
  const message = error instanceof Error ? error.message : String(error);
  return /(?:no tab with id|tab (?:was )?not found|invalid tab id|does not exist)/i.test(message);
}

/**
 * Globally clean up idle tabs. Managed and unmanaged tabs are both considered,
 * but only inactive, unpinned, inaudible tabs in normal windows can qualify.
 */
export async function closeIdleTabs({ chromeApi, hours, dryRun = false, now = () => Date.now(), shouldContinue = () => true }) {
  assertValidIdleHours(hours);
  if (!chromeApi?.windows?.getAll || !chromeApi?.windows?.get || !chromeApi?.tabs?.get || !chromeApi?.tabs?.remove) {
    throw new Error("Chrome tabs/windows APIs are unavailable.");
  }

  const startedAt = now();
  const cutoff = startedAt - hours * HOUR_MS;
  const windows = await chromeApi.windows.getAll({ populate: true });
  const initialCandidates = [];
  const skipped = [];
  const failed = [];

  for (const window of Array.isArray(windows) ? windows : []) {
    for (const tab of Array.isArray(window?.tabs) ? window.tabs : []) {
      const reason = skipReason(tab, window, cutoff);
      if (reason) {
        skipped.push({ ...tabDetails(tab, startedAt), reason });
      } else {
        initialCandidates.push(tabDetails(tab, startedAt));
      }
    }
  }

  const eligible = [];
  const closed = [];

  // Process sequentially so each get/window/get/remove sequence is a fresh
  // safety check immediately before that individual destructive operation.
  for (const candidate of initialCandidates) {
    if (!shouldContinue()) {
      break;
    }
    let currentTab;
    let currentWindow;
    let validatedWindowId;
    try {
      const tabBeforeWindowCheck = await chromeApi.tabs.get(candidate.id);
      validatedWindowId = tabBeforeWindowCheck.windowId;
      currentWindow = await chromeApi.windows.get(validatedWindowId, { populate: false });
      // windows.get can yield while the tab changes protection state or moves.
      // Fetch it again so no stale tab object reaches the removal decision.
      currentTab = await chromeApi.tabs.get(candidate.id);
    } catch (error) {
      if (isVanishedError(error)) {
        skipped.push({ ...candidate, reason: "vanished" });
      } else {
        failed.push({
          ...candidate,
          stage: "revalidate",
          error: error instanceof Error ? error.message : String(error),
        });
      }
      continue;
    }

    if (!shouldContinue()) {
      break;
    }

    const checkedAt = now();
    const details = tabDetails(currentTab, checkedAt);
    if (currentTab.windowId !== validatedWindowId) {
      skipped.push({ ...details, reason: "revalidated-window-changed" });
      continue;
    }

    const reason = skipReason(currentTab, currentWindow, cutoff);
    if (reason) {
      skipped.push({ ...details, reason: `revalidated-${reason}` });
      continue;
    }

    eligible.push(details);
    if (dryRun) {
      continue;
    }
    if (!shouldContinue()) {
      break;
    }

    try {
      await chromeApi.tabs.remove(currentTab.id);
      closed.push(details);
    } catch (error) {
      if (isVanishedError(error)) {
        skipped.push({ ...details, reason: "vanished-before-close" });
      } else {
        failed.push({
          ...details,
          stage: "close",
          error: error instanceof Error ? error.message : String(error),
        });
      }
    }
  }

  return {
    dryRun: Boolean(dryRun),
    hours,
    eligibleCount: eligible.length,
    closedCount: closed.length,
    skippedCount: skipped.length,
    failedCount: failed.length,
    eligible,
    closed,
    skipped,
    failed,
  };
}
