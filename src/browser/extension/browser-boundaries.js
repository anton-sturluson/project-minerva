/** Pure boundary helpers shared by the MV3 worker and unit tests. */

function entriesArray(entries) {
  return Array.from(entries || []);
}

/**
 * Resolve an explicit tab parameter without ever interpreting a numeric string
 * as a Chrome tab id. Integer ids are accepted only when already registered;
 * strings are matched only as exact aliases (aliases happen to normally be tN).
 */
export function resolveManagedTabIdentifier(entries, activeTabId, params = {}) {
  const managed = entriesArray(entries);
  const raw = params.tabId ?? params.alias;

  if (raw == null || (typeof raw === "string" && !raw.trim())) {
    return activeTabId;
  }

  if (Number.isInteger(raw)) {
    if (managed.some((entry) => entry?.tabId === raw)) {
      return raw;
    }
    throw new Error(`Unknown managed tab id "${raw}".`);
  }

  if (typeof raw !== "string") {
    throw new Error("Managed tab identifier must be a registered alias.");
  }

  const alias = raw.trim();
  const entry = managed.find((candidate) => candidate?.alias === alias);
  if (!entry) {
    throw new Error(`Unknown managed tab alias "${alias}".`);
  }
  return entry.tabId;
}

export function assertManagedTabRegistered(entries, tabId) {
  if (!Number.isInteger(tabId) || !entriesArray(entries).some((entry) => entry?.tabId === tabId)) {
    throw new Error(`Tab ${tabId ?? "(none)"} is not a registered managed tab.`);
  }
  return tabId;
}

function errorMessage(error) {
  return error instanceof Error ? error.message : String(error);
}

/**
 * Capture only through a tab-id-specific CDP session. Full-page failure may
 * fall back to a CDP viewport capture of the same target, never to the active
 * tab of a window.
 */
export async function captureTargetViaCdp({
  tabId,
  fullPage,
  format = "png",
  quality = 80,
  captureFullPage,
  captureViewport,
}) {
  if (!fullPage) {
    try {
      return {
        dataUrl: await captureViewport(tabId, format, quality),
        mode: "viewport",
      };
    } catch (error) {
      throw new Error(`Target-specific CDP viewport capture failed for tab ${tabId}: ${errorMessage(error)}`);
    }
  }

  try {
    return await captureFullPage(tabId);
  } catch (fullPageError) {
    try {
      return {
        dataUrl: await captureViewport(tabId, "png", quality),
        mode: "viewport",
        warning: `Full-page CDP capture failed; used target-specific CDP viewport capture instead (${errorMessage(fullPageError)}).`,
      };
    } catch (viewportError) {
      throw new Error(
        `Screenshot capture failed for tab ${tabId}: full-page CDP capture failed (${errorMessage(fullPageError)}); target-specific CDP viewport capture failed (${errorMessage(viewportError)}).`,
      );
    }
  }
}
