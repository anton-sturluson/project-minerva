import { closeIdleTabs } from "./close-idle.js";
import {
  assertManagedTabRegistered,
  captureTargetViaCdp,
  resolveManagedTabIdentifier,
} from "./browser-boundaries.js";
import { SerializedStateStore, SerialTaskQueue } from "./runtime-state.js";

const BRIDGE_URL = "ws://127.0.0.1:19224";
const BRIDGE_PROTOCOL_VERSION = 1;
const PREVIEW_CHARS = 500;
const MAX_FULL_PAGE_DIMENSION = 16384;
const BRIDGE_RECONNECT_ALARM = "browser-v2-bridge-reconnect";
const BRIDGE_RECONNECT_PERIOD_MINUTES = 0.5;

let socket = null;
let reconnectTimer = null;
let keepaliveTimer = null;
let reconnectDelayMs = 1000;
const requestQueue = new SerialTaskQueue();
const cancelledRequestsBySocket = new WeakMap();

let managedTabs = new Map();
let activeTabId = null;
let nextTabAliasId = 0;
const tabSessionStates = new Map();
let stateMutationBatchDepth = 0;
let stateMutationBatchDirty = false;

function createTabState() {
  return {
    snapshotBaseline: null,
    refMap: {},
    nextRefId: 1,
    dialog: null,
  };
}

function getTabState(tabId) {
  if (!Number.isInteger(tabId)) {
    return createTabState();
  }
  if (!tabSessionStates.has(tabId)) {
    tabSessionStates.set(tabId, createTabState());
  }
  return tabSessionStates.get(tabId);
}

function clearSessionState(tabId) {
  if (!Number.isInteger(tabId)) {
    return;
  }
  tabSessionStates.set(tabId, createTabState());
}

function clearRefMap(tabId) {
  const tabState = getTabState(tabId);
  tabState.refMap = {};
  tabState.nextRefId = 1;
}

function managedTabRecordFromTab(tab, alias) {
  return {
    tabId: tab.id,
    windowId: Number.isInteger(tab.windowId) ? tab.windowId : null,
    url: tab.url || "about:blank",
    title: tab.title || "",
    alias,
  };
}

function getNextTabAlias() {
  const alias = `t${nextTabAliasId}`;
  nextTabAliasId += 1;
  return alias;
}

function refreshNextTabAliasId() {
  const aliases = Array.from(managedTabs.values())
    .map((entry) => {
      const match = /^t(\d+)$/.exec(entry.alias || "");
      return match ? Number.parseInt(match[1], 10) : -1;
    })
    .filter((value) => Number.isFinite(value));
  nextTabAliasId = aliases.length > 0 ? Math.max(...aliases) + 1 : 0;
}

function getManagedTabEntry(tabId) {
  return Number.isInteger(tabId) ? managedTabs.get(tabId) ?? null : null;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function throwIfCancelled(context, operation = "operation") {
  if (context?.shouldContinue && !context.shouldContinue()) {
    throw new Error(`Command cancelled before ${operation}.`);
  }
}

async function cancellableSleep(ms, context) {
  const deadline = Date.now() + ms;
  while (Date.now() < deadline) {
    throwIfCancelled(context, "wait completed");
    await sleep(Math.min(100, Math.max(0, deadline - Date.now())));
  }
  throwIfCancelled(context, "wait completed");
}

function postActionDelay(minMs = 300, maxMs = 800) {
  const minimum = Number.isFinite(minMs) ? Math.max(0, Math.floor(minMs)) : 300;
  const maximum = Number.isFinite(maxMs) ? Math.max(minimum, Math.floor(maxMs)) : 800;
  const delay = minimum === maximum ? minimum : Math.floor(Math.random() * (maximum - minimum + 1)) + minimum;
  return sleep(delay);
}

function log(...parts) {
  console.log("[browser-extension]", ...parts);
}

function sendTo(targetSocket, payload) {
  if (!targetSocket || targetSocket.readyState !== WebSocket.OPEN) {
    return;
  }
  targetSocket.send(JSON.stringify(payload));
}

const statePersistence = new SerializedStateStore({
  storage: chrome.storage.session,
  keys: ["managedTabs", "activeTabId"],
  empty: () => ({ managedTabs: [], activeTabId: null }),
  read: () => ({
    managedTabs: Array.from(managedTabs.values()),
    activeTabId,
  }),
  apply: (stored) => {
    const storedTabs = Array.isArray(stored?.managedTabs) ? stored.managedTabs : [];
    managedTabs = new Map(
      storedTabs
        .filter((entry) => Number.isInteger(entry?.tabId) && typeof entry?.alias === "string")
        .map((entry) => [
          entry.tabId,
          {
            tabId: entry.tabId,
            windowId: Number.isInteger(entry.windowId) ? entry.windowId : null,
            url: typeof entry.url === "string" ? entry.url : "about:blank",
            title: typeof entry.title === "string" ? entry.title : "",
            alias: entry.alias,
          },
        ]),
    );
    activeTabId = Number.isInteger(stored?.activeTabId) ? stored.activeTabId : null;
    if (activeTabId != null && !managedTabs.has(activeTabId)) {
      activeTabId = managedTabs.keys().next().value ?? null;
    }
    refreshNextTabAliasId();
  },
});

async function loadState() {
  await statePersistence.load();
}

async function saveState() {
  if (stateMutationBatchDepth > 0) {
    stateMutationBatchDirty = true;
    return;
  }
  await statePersistence.save();
}

function beginStateMutationBatch() {
  stateMutationBatchDepth += 1;
}

async function endStateMutationBatch() {
  stateMutationBatchDepth = Math.max(0, stateMutationBatchDepth - 1);
  if (stateMutationBatchDepth === 0 && stateMutationBatchDirty) {
    stateMutationBatchDirty = false;
    await statePersistence.save();
  }
}

async function addManagedTab(tab) {
  if (!tab || tab.id == null) {
    return;
  }
  await loadState();
  const existing = getManagedTabEntry(tab.id);
  managedTabs.set(tab.id, managedTabRecordFromTab(tab, existing?.alias || getNextTabAlias()));
  activeTabId = tab.id;
  await saveState();
}

async function updateManagedTab(tab) {
  if (!tab || tab.id == null) {
    return;
  }
  await loadState();
  const existing = getManagedTabEntry(tab.id);
  if (!existing) {
    return;
  }
  managedTabs.set(tab.id, managedTabRecordFromTab(tab, existing.alias));
  await saveState();
}

async function removeManagedTabs(tabIds) {
  await loadState();
  let changed = false;
  for (const tabId of tabIds) {
    if (!Number.isInteger(tabId)) {
      continue;
    }
    const wasManaged = managedTabs.delete(tabId);
    if (wasManaged) {
      changed = true;
      tabSessionStates.delete(tabId);
      void debuggerPool.forceDetach(tabId).catch(() => undefined);
    }
    if (activeTabId === tabId) {
      activeTabId = managedTabs.keys().next().value ?? null;
      changed = true;
    }
  }
  if (changed) {
    await saveState();
  }
}

async function removeManagedTab(tabId) {
  await removeManagedTabs([tabId]);
}

async function setActiveTab(tabId) {
  await loadState();
  if (!Number.isInteger(tabId) || !managedTabs.has(tabId)) {
    throw new Error(`No managed tab found for ${tabId}.`);
  }
  activeTabId = tabId;
  await saveState();
}

async function resolveTabParam(params = {}) {
  await loadState();
  return resolveManagedTabIdentifier(managedTabs.values(), activeTabId, params);
}

function listManagedTabs() {
  return Array.from(managedTabs.values()).map((entry) => ({
    alias: entry.alias,
    tabId: entry.tabId,
    url: entry.url,
    title: entry.title,
    active: entry.tabId === activeTabId,
  }));
}

function scheduleReconnect() {
  if (reconnectTimer) {
    return;
  }
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connectBridge();
  }, reconnectDelayMs);
  reconnectDelayMs = Math.min(reconnectDelayMs * 2, 10000);
}

function connectBridge() {
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
    return;
  }

  const connection = new WebSocket(BRIDGE_URL);
  socket = connection;
  cancelledRequestsBySocket.set(connection, new Set());

  connection.addEventListener("open", () => {
    reconnectDelayMs = 1000;
    sendTo(connection, {
      type: "hello",
      source: "browser-cli-extension",
      protocolVersion: BRIDGE_PROTOCOL_VERSION,
    });
    if (keepaliveTimer) {
      clearInterval(keepaliveTimer);
    }
    keepaliveTimer = setInterval(() => {
      sendTo(connection, {
        type: "keepalive",
        source: "browser-cli-extension",
        protocolVersion: BRIDGE_PROTOCOL_VERSION,
      });
    }, 20_000);
    log("Connected to bridge");
  });

  connection.addEventListener("message", (event) => {
    handleBridgeMessage(connection, event.data);
  });

  connection.addEventListener("close", () => {
    if (socket === connection) {
      socket = null;
    }
    if (keepaliveTimer) {
      clearInterval(keepaliveTimer);
      keepaliveTimer = null;
    }
    log("Bridge socket closed. Reconnecting...");
    scheduleReconnect();
  });

  connection.addEventListener("error", () => {
    log("Bridge socket error. Reconnecting...");
    scheduleReconnect();
  });
}

function ensureReconnectAlarm() {
  chrome.alarms.create(BRIDGE_RECONNECT_ALARM, {
    delayInMinutes: BRIDGE_RECONNECT_PERIOD_MINUTES,
    periodInMinutes: BRIDGE_RECONNECT_PERIOD_MINUTES,
  });
}

function isRestrictedUrl(url) {
  if (typeof url !== "string" || !url) {
    return false;
  }

  const lowered = url.toLowerCase();
  if (lowered === "about:blank") {
    return false;
  }

  return (
    lowered.startsWith("chrome://") ||
    lowered.startsWith("chrome-extension://") ||
    lowered.startsWith("devtools://") ||
    lowered.startsWith("edge://") ||
    lowered.startsWith("view-source:") ||
    lowered.startsWith("about:")
  );
}

function normalizeUrl(value) {
  const raw = String(value || "").trim();
  if (!raw) {
    return "";
  }
  if (/^[a-zA-Z][a-zA-Z\d+\-.]*:/.test(raw)) {
    return raw;
  }
  return `https://${raw}`;
}

function isProbablySelector(target) {
  return (
    target.startsWith(".") ||
    target.startsWith("#") ||
    target.startsWith("[") ||
    target.startsWith("/") ||
    target.startsWith("xpath=") ||
    target.startsWith("css=") ||
    target.startsWith("text=") ||
    target.startsWith("role=") ||
    /[\s>+~:[\].#=]/.test(target)
  );
}

function resolveTargetRef(tabId, target) {
  const raw = String(target || "").trim();
  const tabState = getTabState(tabId);
  if (/^e\d+$/.test(raw) && tabState.refMap[raw]) {
    return tabState.refMap[raw];
  }
  return raw;
}

async function getActiveTab() {
  const tabs = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  if (tabs[0]?.id != null) {
    return tabs[0];
  }

  const fallback = await chrome.tabs.query({ active: true, currentWindow: true });
  if (fallback[0]?.id != null) {
    return fallback[0];
  }

  const anyActive = await chrome.tabs.query({ active: true });
  if (anyActive[0]?.id != null) {
    return anyActive[0];
  }

  throw new Error("No active tab found. Focus a Chrome window and retry.");
}

async function createManagedWindow(context = {}) {
  throwIfCancelled(context, "window creation");
  const createdWindow = await chrome.windows.create({
    url: "about:blank",
    focused: true,
    type: "normal",
  });

  let tab = createdWindow.tabs?.find((candidate) => candidate?.id != null) ?? null;
  if (!tab && Number.isInteger(createdWindow.id)) {
    const tabs = await chrome.tabs.query({ windowId: createdWindow.id });
    tab = tabs.find((candidate) => candidate?.id != null) ?? null;
  }

  if (!tab || tab.id == null) {
    throw new Error("Failed to create automation window tab.");
  }

  await addManagedTab(tab);
  return tab;
}

async function getManagedTab(options = {}) {
  const { allowFallback = true, requireScriptable = false } = options;
  await loadState();
  const explicitTabId = Number.isInteger(options.tabId) ? options.tabId : null;
  if (explicitTabId != null) {
    assertManagedTabRegistered(managedTabs.values(), explicitTabId);
  }
  const candidateIds = [];
  if (explicitTabId != null) {
    candidateIds.push(explicitTabId);
  } else if (activeTabId != null) {
    candidateIds.push(activeTabId);
  }

  for (const tabId of managedTabs.keys()) {
    if (!candidateIds.includes(tabId)) {
      candidateIds.push(tabId);
    }
  }

  for (const candidateId of candidateIds) {
    try {
      const tab = await chrome.tabs.get(candidateId);
      await updateManagedTab(tab);
      if (explicitTabId == null && activeTabId !== tab.id) {
        await setActiveTab(tab.id);
      }
      if (requireScriptable && isRestrictedUrl(tab.url || "")) {
        throw new Error(
          `Managed tab is on a restricted URL (${tab.url || "unknown"}). Run browser open <url> to move it to a normal page.`,
        );
      }
      return tab;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      if (message.includes("restricted URL")) {
        throw error;
      }
      if (managedTabs.has(candidateId)) {
        await removeManagedTab(candidateId);
      }
      if (explicitTabId != null) {
        throw new Error(`Managed tab ${candidateId} is no longer available.`);
      }
    }
  }

  if (managedTabs.size === 0 && allowFallback) {
    const managed = await createManagedWindow(options.context);

    if (requireScriptable && isRestrictedUrl(managed.url || "")) {
      throw new Error(
        `Managed tab is on a restricted URL (${managed.url || "unknown"}). Open a regular http/https page first.`,
      );
    }

    return managed;
  }

  throw new Error("No managed tab available. Run browser open <url> first.");
}

function waitForTabComplete(tabId, timeoutMs = 10000, context = {}) {
  return new Promise((resolve, reject) => {
    let done = false;
    const deadline = Date.now() + timeoutMs;

    const finish = (value) => {
      if (done) {
        return;
      }
      done = true;
      chrome.tabs.onUpdated.removeListener(onUpdated);
      clearInterval(pollTimer);
      resolve(value);
    };

    const fail = (message) => {
      if (done) {
        return;
      }
      done = true;
      chrome.tabs.onUpdated.removeListener(onUpdated);
      clearInterval(pollTimer);
      reject(new Error(message));
    };

    const checkCurrent = async () => {
      try {
        throwIfCancelled(context, "navigation wait completed");
        const current = await chrome.tabs.get(tabId);
        if (current.status === "complete") {
          finish(current);
          return;
        }
        if (Date.now() > deadline) {
          fail("Timed out waiting for tab to finish loading.");
        }
      } catch {
        fail("Tab is no longer available.");
      }
    };

    const onUpdated = (updatedTabId, changeInfo, updatedTab) => {
      if (updatedTabId === tabId && changeInfo.status === "complete") {
        finish(updatedTab);
      }
    };

    chrome.tabs.onUpdated.addListener(onUpdated);

    const pollTimer = setInterval(() => {
      void checkCurrent();
    }, 200);

    void checkCurrent();
  });
}

async function runInTab(tabId, func, args = []) {
  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId },
      func,
      args,
    });
    return results?.[0]?.result;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new Error(`Cannot execute in managed tab: ${message}`);
  }
}

async function waitForSelector(tabId, selector, timeoutMs = 10000, context = {}) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    throwIfCancelled(context, "selector wait completed");
    const visible = await runInTab(
      tabId,
      (targetSelector) => {
        let node = null;
        try {
          node = document.querySelector(targetSelector);
        } catch {
          return false;
        }
        if (!node) {
          return false;
        }
        const rect = node.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
      },
      [selector],
    );
    if (visible) {
      return;
    }
    await cancellableSleep(150, context);
  }
  throwIfCancelled(context, "selector wait completed");
  throw new Error(`Timed out waiting for selector "${selector}".`);
}

async function readPreview(tabId) {
  try {
    const data = await runInTab(
      tabId,
      (previewChars) => {
        const preview = (document.body?.innerText || "")
          .replace(/\s+/g, " ")
          .trim()
          .slice(0, previewChars);
        return {
          title: document.title || "(untitled)",
          url: window.location.href,
          preview,
        };
      },
      [PREVIEW_CHARS],
    );
    return data || { title: "", url: "about:blank", preview: "" };
  } catch {
    const tab = await chrome.tabs.get(tabId);
    return {
      title: tab.title || "(untitled)",
      url: tab.url || "about:blank",
      preview: "[Preview unavailable for this page]",
    };
  }
}

function axValue(raw) {
  if (raw == null) {
    return null;
  }
  if (typeof raw === "object" && raw !== null) {
    if (Object.prototype.hasOwnProperty.call(raw, "value")) {
      return raw.value;
    }
    if (Object.prototype.hasOwnProperty.call(raw, "type")) {
      return raw.type;
    }
  }
  return raw;
}

function readAxProperty(node, name) {
  const match = Array.isArray(node?.properties) ? node.properties.find((property) => property?.name === name) : null;
  return match ? axValue(match.value) : null;
}

function axRoleName(node) {
  return String(axValue(node?.role) || "").trim();
}

function axNodeName(node) {
  return String(axValue(node?.name) || "").replace(/\s+/g, " ").trim();
}

function shouldSkipAxNode(node) {
  if (!node || node.ignored) {
    return true;
  }
  const role = axRoleName(node).toLowerCase();
  return role === "none" || role === "presentation" || role === "inlinetextbox";
}

function serializeAxNode(node) {
  const roleMap = {
    rootwebarea: "page",
    webarea: "page",
    statictext: "text",
    textfield: "textbox",
    textbox: "textbox",
  };
  const role = axRoleName(node);
  const normalizedRole = roleMap[role.toLowerCase()] || role.toLowerCase() || "node";
  const name = axNodeName(node);
  const parts = [normalizedRole];
  if (name) {
    parts.push(`"${name}"`);
  }

  const states = [];
  const checked = readAxProperty(node, "checked");
  const selected = readAxProperty(node, "selected");
  const expanded = readAxProperty(node, "expanded");
  const required = readAxProperty(node, "required");
  const editable = readAxProperty(node, "editable");
  const level = readAxProperty(node, "level");
  const current = readAxProperty(node, "current");
  const value = axValue(node?.value);
  const restriction = readAxProperty(node, "restriction");

  if (checked !== null) {
    states.push(`checked=${checked}`);
  }
  if (selected !== null) {
    states.push(`selected=${selected}`);
  }
  if (expanded !== null) {
    states.push(`expanded=${expanded}`);
  }
  if (restriction === "disabled") {
    states.push("disabled");
  }
  if (required === true) {
    states.push("required");
  }
  if (value != null && `${value}`.trim()) {
    states.push(`value="${String(value).replace(/\s+/g, " ").trim()}"`);
  }
  if (level != null) {
    states.push(`level=${level}`);
  }
  if (current != null) {
    states.push(`current=${current}`);
  }
  if (editable != null) {
    states.push("editable");
  }

  return `${parts.join(" ")}${states.length > 0 ? ` [${states.join("] [")}]` : ""}`;
}

function buildSnapshotPayload(nodes, options = {}) {
  const depthLimit = Number.isFinite(options.depth) && options.depth >= 0 ? options.depth : Number.POSITIVE_INFINITY;
  const targetBackendNodeId = options.backendNodeId ?? null;
  const nodeMap = new Map(nodes.map((node) => [node.nodeId, node]));
  const parentIds = new Set();
  for (const node of nodes) {
    for (const childId of node.childIds || []) {
      parentIds.add(childId);
    }
  }

  let root =
    (targetBackendNodeId != null && nodes.find((node) => node.backendDOMNodeId === targetBackendNodeId)) ||
    nodes.find((node) => !parentIds.has(node.nodeId)) ||
    nodes[0] ||
    null;

  if (!root) {
    return { lines: [], entries: [] };
  }

  const lines = [];
  const entries = [];

  const visit = (node, depth, path) => {
    if (!node) {
      return;
    }
    const skip = shouldSkipAxNode(node);
    const nextPathBase = path.slice();
    if (!skip) {
      if (depth <= depthLimit) {
        const line = `${"  ".repeat(depth)}${serializeAxNode(node)}`;
        lines.push(line);
        entries.push({
          key: `${path.join(".")}:${axRoleName(node)}:${axNodeName(node)}`,
          role: axRoleName(node),
          name: axNodeName(node),
          state: serializeAxNode(node),
          path: path.join("."),
        });
      }
    }

    const childDepth = skip ? depth : depth + 1;
    if (childDepth > depthLimit) {
      return;
    }
    const childIds = Array.isArray(node.childIds) ? node.childIds : [];
    childIds.forEach((childId, index) => {
      const child = nodeMap.get(childId);
      visit(child, childDepth, skip ? path.concat(index) : nextPathBase.concat(index));
    });
  };

  visit(root, 0, [0]);
  return { lines, entries };
}

function parseSerializedState(state) {
  const value = String(state || "").trim();
  const bracketIndex = value.indexOf(" [");
  return {
    label: bracketIndex === -1 ? value : value.slice(0, bracketIndex).trim(),
    attributes: Array.from(value.matchAll(/\[([^\]]+)\]/g)).map((match) => match[1].trim()),
  };
}

function formatChangedState(previousState, nextState) {
  const previous = parseSerializedState(previousState);
  const next = parseSerializedState(nextState);
  if (previous.label && previous.label === next.label) {
    const previousAttributes = previous.attributes.join("] [") || "state unavailable";
    const nextAttributes = next.attributes.join("] [") || "state unavailable";
    return `${next.label} [${previousAttributes} -> ${nextAttributes}]`;
  }
  return `${previousState} -> ${nextState}`;
}

function computeStateChanges(beforeSnapshot, afterSnapshot, limit = 20) {
  if ((beforeSnapshot?.snapshot || "") === (afterSnapshot?.snapshot || "")) {
    return ["No state changes detected."];
  }

  const previousEntries = Array.isArray(beforeSnapshot?.entries) ? beforeSnapshot.entries : [];
  const nextEntries = Array.isArray(afterSnapshot?.entries) ? afterSnapshot.entries : [];
  const previousMap = new Map(previousEntries.map((entry) => [entry.key, entry]));
  const nextMap = new Map(nextEntries.map((entry) => [entry.key, entry]));
  const changes = [];

  for (const [key, nextEntry] of nextMap.entries()) {
    const previousEntry = previousMap.get(key);
    if (!previousEntry) {
      changes.push(`ADDED: ${nextEntry.state}`);
    } else if (previousEntry.state !== nextEntry.state) {
      changes.push(`CHANGED: ${formatChangedState(previousEntry.state, nextEntry.state)}`);
    }
    if (changes.length >= limit) {
      return changes;
    }
  }

  for (const [key, previousEntry] of previousMap.entries()) {
    if (!nextMap.has(key)) {
      changes.push(`REMOVED: ${previousEntry.state}`);
    }
    if (changes.length >= limit) {
      return changes;
    }
  }

  return changes.length > 0 ? changes : ["No state changes detected."];
}

async function captureWriteStateChanges(tabId, action) {
  let beforeSnapshot = null;
  try {
    beforeSnapshot = await captureAxTree(tabId, { depth: 3 });
  } catch (error) {
    log("Pre-action AX snapshot failed:", error instanceof Error ? error.message : String(error));
  }

  const result = await action();

  if (!beforeSnapshot) {
    return {
      result,
      stateChanges: ["Unable to capture pre-action state."],
    };
  }

  try {
    const afterSnapshot = await captureAxTree(tabId, { depth: 3 });
    return {
      result,
      stateChanges: computeStateChanges(beforeSnapshot, afterSnapshot),
    };
  } catch (error) {
    return {
      result,
      stateChanges: [`Unable to capture post-action state: ${error instanceof Error ? error.message : String(error)}`],
    };
  }
}

async function maybePostActionDelay(params) {
  if (params?.noDelay) {
    return;
  }
  await postActionDelay();
}

async function captureAxTree(tabId, options = {}) {
  return withDebugger(tabId, async (target) => {
    await chrome.debugger.sendCommand(target, "Accessibility.enable");
    let response;
    let backendNodeId = null;

    if (typeof options.scope === "string" && options.scope.trim()) {
      const documentNode = await chrome.debugger.sendCommand(target, "DOM.getDocument", { depth: -1, pierce: true });
      const rootNodeId = documentNode?.root?.nodeId;
      if (!rootNodeId) {
        throw new Error("Unable to resolve DOM document for snapshot.");
      }
      const query = await chrome.debugger.sendCommand(target, "DOM.querySelector", {
        nodeId: rootNodeId,
        selector: options.scope,
      });
      if (!query?.nodeId) {
        throw new Error(`No element matches scope selector "${options.scope}".`);
      }
      const described = await chrome.debugger.sendCommand(target, "DOM.describeNode", { nodeId: query.nodeId });
      backendNodeId = described?.node?.backendNodeId ?? null;
      response = await chrome.debugger.sendCommand(target, "Accessibility.getPartialAXTree", {
        nodeId: query.nodeId,
        fetchRelatives: true,
      });
    } else {
      response = await chrome.debugger.sendCommand(target, "Accessibility.getFullAXTree");
    }

    const nodes = Array.isArray(response?.nodes) ? response.nodes : [];
    const payload = buildSnapshotPayload(nodes, {
      depth: options.depth,
      backendNodeId,
    });
    return {
      snapshot: payload.lines.join("\n"),
      entries: payload.entries,
    };
  });
}

class DebuggerPool {
  constructor() {
    this.sessions = new Map();
    chrome.debugger.onEvent.addListener((source, method, params) => {
      const tabId = source?.tabId;
      if (!Number.isInteger(tabId)) {
        return;
      }
      const tabState = getTabState(tabId);
      if (method === "Page.javascriptDialogOpening") {
        tabState.dialog = {
          open: true,
          type: params?.type || "dialog",
          message: params?.message || "",
          defaultPrompt: params?.defaultPrompt || "",
          hasBrowserHandler: Boolean(params?.hasBrowserHandler),
        };
      }
      if (method === "Page.javascriptDialogClosed") {
        tabState.dialog = null;
      }
    });
  }

  getSession(tabId) {
    if (!this.sessions.has(tabId)) {
      this.sessions.set(tabId, {
        target: { tabId },
        attached: false,
        refCount: 0,
        queue: Promise.resolve(),
        idleTimer: null,
      });
    }
    return this.sessions.get(tabId);
  }

  async ensureAttached(session) {
    if (session.attached) {
      return;
    }
    await chrome.debugger.attach(session.target, "1.3");
    session.attached = true;
    await chrome.debugger.sendCommand(session.target, "Page.enable");
    await chrome.debugger.sendCommand(session.target, "Runtime.enable");
    await chrome.debugger.sendCommand(session.target, "DOM.enable");
    // Note: Input domain has no "enable" method — it's always available once debugger is attached.
  }

  scheduleDetach(session) {
    if (session.idleTimer) {
      clearTimeout(session.idleTimer);
    }
    session.idleTimer = setTimeout(() => {
      void this.forceDetach(session.target.tabId);
    }, 2000);
  }

  async forceDetach(tabId) {
    const session = this.getSession(tabId);
    if (session.idleTimer) {
      clearTimeout(session.idleTimer);
      session.idleTimer = null;
    }
    if (!session.attached) {
      return;
    }
    session.refCount = 0;
    try {
      await chrome.debugger.detach(session.target);
    } catch {
      // Ignore detach failures.
    }
    session.attached = false;
    getTabState(tabId).dialog = null;
  }

  async run(tabId, callback, timeoutMs = 10000) {
    const session = this.getSession(tabId);
    if (session.idleTimer) {
      clearTimeout(session.idleTimer);
      session.idleTimer = null;
    }

    const operation = async () => {
      await this.ensureAttached(session);
      session.refCount += 1;
      try {
        return await Promise.race([
          callback(session.target),
          new Promise((_, reject) => {
            setTimeout(() => reject(new Error("Debugger operation timed out.")), timeoutMs);
          }),
        ]);
      } catch (error) {
        if (error instanceof Error && error.message.includes("timed out")) {
          log("Debugger session timed out; forcing detach for tab", tabId);
          await this.forceDetach(tabId);
        }
        throw error;
      } finally {
        session.refCount = Math.max(0, session.refCount - 1);
        if (session.refCount === 0) {
          this.scheduleDetach(session);
        }
      }
    };

    const queued = session.queue.then(operation, operation);
    session.queue = queued.catch(() => undefined);
    return queued;
  }
}

const debuggerPool = new DebuggerPool();

async function withDebugger(tabId, callback, timeoutMs = 10000) {
  return debuggerPool.run(tabId, callback, timeoutMs);
}

async function getPlatformModifier() {
  const info = await chrome.runtime.getPlatformInfo();
  return info.os === "mac" ? 4 : 2;
}

function keyDescriptionForCharacter(character) {
  if (character === "\n") {
    return {
      key: "Enter",
      code: "Enter",
      windowsVirtualKeyCode: 13,
      text: "\r",
      unmodifiedText: "\r",
    };
  }

  if (character === "\t") {
    return {
      key: "Tab",
      code: "Tab",
      windowsVirtualKeyCode: 9,
      text: "\t",
      unmodifiedText: "\t",
    };
  }

  const upper = character.toUpperCase();
  const lower = character.toLowerCase();
  if (/^[a-z]$/i.test(character)) {
    return {
      key: character,
      code: `Key${upper}`,
      windowsVirtualKeyCode: upper.charCodeAt(0),
      text: character,
      unmodifiedText: lower,
    };
  }

  if (/^[0-9]$/.test(character)) {
    return {
      key: character,
      code: `Digit${character}`,
      windowsVirtualKeyCode: character.charCodeAt(0),
      text: character,
      unmodifiedText: character,
    };
  }

  return {
    key: character,
    code: "Unidentified",
    windowsVirtualKeyCode: character.charCodeAt(0),
    text: character,
    unmodifiedText: character,
  };
}

async function dispatchCharacter(target, character) {
  const description = keyDescriptionForCharacter(character);
  // keyDown without text/unmodifiedText — otherwise Chrome inserts the char twice
  // (once on keyDown with text, once on the char event).
  await chrome.debugger.sendCommand(target, "Input.dispatchKeyEvent", {
    type: "keyDown",
    key: description.key,
    code: description.code,
    windowsVirtualKeyCode: description.windowsVirtualKeyCode,
  });
  await chrome.debugger.sendCommand(target, "Input.dispatchKeyEvent", {
    type: "char",
    ...description,
  });
  await chrome.debugger.sendCommand(target, "Input.dispatchKeyEvent", {
    type: "keyUp",
    key: description.key,
    code: description.code,
    windowsVirtualKeyCode: description.windowsVirtualKeyCode,
  });
}

async function dispatchShortcut(target, options) {
  await chrome.debugger.sendCommand(target, "Input.dispatchKeyEvent", {
    type: "rawKeyDown",
    ...options,
  });
  await chrome.debugger.sendCommand(target, "Input.dispatchKeyEvent", {
    type: "keyUp",
    key: options.key,
    code: options.code,
    windowsVirtualKeyCode: options.windowsVirtualKeyCode,
    modifiers: options.modifiers,
  });
}

async function dispatchBackspace(target) {
  await chrome.debugger.sendCommand(target, "Input.dispatchKeyEvent", {
    type: "rawKeyDown",
    key: "Backspace",
    code: "Backspace",
    windowsVirtualKeyCode: 8,
  });
  await chrome.debugger.sendCommand(target, "Input.dispatchKeyEvent", {
    type: "keyUp",
    key: "Backspace",
    code: "Backspace",
    windowsVirtualKeyCode: 8,
  });
}

async function resolveWritableTarget(tabId, target, index) {
  return runInTab(
    tabId,
    (rawTarget, rawIndex, selectorHint) => {
      const normalize = (value) => String(value || "").replace(/\s+/g, " ").trim();
      const cssEscape = (value) => (window.CSS && typeof window.CSS.escape === "function" ? window.CSS.escape(value) : value);
      const isVisible = (node) => {
        if (!(node instanceof Element)) {
          return false;
        }
        const rect = node.getBoundingClientRect();
        const style = window.getComputedStyle(node);
        return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";
      };
      const uniqueSelector = (element) => {
        if (!(element instanceof Element)) {
          return null;
        }
        if (element.id) {
          return `#${cssEscape(element.id)}`;
        }
        for (const attr of ["data-e2e", "data-testid", "name", "aria-label", "placeholder"]) {
          const value = element.getAttribute(attr);
          if (value && document.querySelectorAll(`${element.tagName.toLowerCase()}[${attr}="${cssEscape(value)}"]`).length === 1) {
            return `${element.tagName.toLowerCase()}[${attr}="${cssEscape(value)}"]`;
          }
        }
        const parts = [];
        let current = element;
        while (current && current instanceof Element && current !== document.body) {
          let part = current.tagName.toLowerCase();
          if (current.classList.length > 0) {
            part += `.${Array.from(current.classList)
              .slice(0, 2)
              .map((value) => cssEscape(value))
              .join(".")}`;
          }
          const siblings = current.parentElement
            ? Array.from(current.parentElement.children).filter((child) => child.tagName === current.tagName)
            : [];
          if (siblings.length > 1) {
            part += `:nth-of-type(${siblings.indexOf(current) + 1})`;
          }
          parts.unshift(part);
          const selector = parts.join(" > ");
          if (document.querySelectorAll(selector).length === 1) {
            return selector;
          }
          current = current.parentElement;
        }
        return parts.join(" > ") || element.tagName.toLowerCase();
      };

      const candidateSelector = "input, textarea, [contenteditable='true'], [contenteditable=''], [role='textbox'], [aria-label], [name]";
      let matches = [];
      if (selectorHint) {
        try {
          matches = Array.from(document.querySelectorAll(rawTarget));
        } catch {
          matches = [];
        }
      }

      const targetText = normalize(rawTarget).toLowerCase();
      if (matches.length === 0 && targetText) {
        const exact = [];
        const partial = [];
        for (const node of Array.from(document.querySelectorAll(candidateSelector))) {
          const text = normalize(
            node.innerText ||
              node.textContent ||
              node.getAttribute("aria-label") ||
              node.getAttribute("name") ||
              node.getAttribute("placeholder") ||
              node.getAttribute("value"),
          );
          if (!text) {
            continue;
          }
          const lowered = text.toLowerCase();
          if (lowered === targetText) {
            exact.push(node);
          } else if (lowered.includes(targetText)) {
            partial.push(node);
          }
        }
        matches = exact.length > 0 ? exact : partial;
      }

      const suggestions = Array.from(document.querySelectorAll(candidateSelector))
        .map((node) =>
          normalize(
            node.innerText ||
              node.textContent ||
              node.getAttribute("aria-label") ||
              node.getAttribute("name") ||
              node.getAttribute("placeholder"),
          ),
        )
        .filter(Boolean)
        .slice(0, 8);

      if (matches.length === 0) {
        return {
          ok: false,
          error: suggestions.length > 0 ? `No writable element matching "${rawTarget}". Available inputs: ${suggestions.map((item) => `"${item}"`).join(", ")}` : `No writable element matching "${rawTarget}".`,
        };
      }

      const indexValue = Number.isFinite(rawIndex) ? rawIndex : 0;
      if (indexValue >= matches.length) {
        return {
          ok: false,
          error: `Match index ${indexValue} is out of range for "${rawTarget}" (${matches.length} matches).`,
        };
      }

      const element = matches[indexValue];
      const writable =
        element instanceof HTMLInputElement ||
        element instanceof HTMLTextAreaElement ||
        (element instanceof HTMLElement && element.isContentEditable) ||
        element.getAttribute("role") === "textbox";
      if (!writable) {
        return { ok: false, error: `Element "${rawTarget}" is not a writable input.` };
      }

      return {
        ok: true,
        selector: uniqueSelector(element),
        description: normalize(
          element.getAttribute("aria-label") ||
            element.getAttribute("name") ||
            element.getAttribute("placeholder") ||
            element.innerText ||
            element.textContent ||
            rawTarget,
        ),
      };
    },
    [target, index, isProbablySelector(target)],
  );
}

async function readElementValue(tabId, selector) {
  return runInTab(
    tabId,
    (targetSelector) => {
      if (!targetSelector) {
        return "";
      }
      const element = document.querySelector(targetSelector);
      if (!element) {
        return "";
      }
      if (element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement) {
        return element.value;
      }
      return (element.innerText || element.textContent || "").replace(/\s+/g, " ").trim();
    },
    [selector],
  );
}

async function resolveUploadTarget(tabId, target) {
  return runInTab(
    tabId,
    (rawTarget) => {
      const cssEscape = (value) => (window.CSS && typeof window.CSS.escape === "function" ? window.CSS.escape(value) : value);
      const normalize = (value) => String(value || "").replace(/\s+/g, " ").trim();
      const selectorHint = rawTarget && (rawTarget.startsWith(".") || rawTarget.startsWith("#") || rawTarget.startsWith("[") || /[\s>+~:[\].#=]/.test(rawTarget));
      const buildSelector = (element) => {
        if (!(element instanceof Element)) {
          return null;
        }
        if (element.id) {
          return `#${cssEscape(element.id)}`;
        }
        for (const attr of ["data-e2e", "data-testid", "name", "accept"]) {
          const value = element.getAttribute(attr);
          if (value && document.querySelectorAll(`${element.tagName.toLowerCase()}[${attr}="${cssEscape(value)}"]`).length === 1) {
            return `${element.tagName.toLowerCase()}[${attr}="${cssEscape(value)}"]`;
          }
        }
        const parts = [];
        let current = element;
        while (current && current instanceof Element && current !== document.body) {
          let part = current.tagName.toLowerCase();
          const siblings = current.parentElement
            ? Array.from(current.parentElement.children).filter((child) => child.tagName === current.tagName)
            : [];
          if (siblings.length > 1) {
            part += `:nth-of-type(${siblings.indexOf(current) + 1})`;
          }
          parts.unshift(part);
          const selector = parts.join(" > ");
          if (document.querySelectorAll(selector).length === 1) {
            return selector;
          }
          current = current.parentElement;
        }
        return parts.join(" > ") || element.tagName.toLowerCase();
      };

      const isFileInput = (node) => node instanceof HTMLInputElement && node.type === "file";
      let element = null;
      if (selectorHint) {
        try {
          element = document.querySelector(rawTarget);
        } catch {
          element = null;
        }
      } else if (typeof rawTarget === "string" && rawTarget.trim()) {
        const exact = Array.from(document.querySelectorAll("input[type='file']")).find((node) => {
          const label = normalize(node.getAttribute("aria-label") || node.getAttribute("name") || node.getAttribute("accept"));
          return label.toLowerCase() === rawTarget.trim().toLowerCase();
        });
        element = exact || null;
      }

      let input = null;
      if (isFileInput(element)) {
        input = element;
      } else if (element instanceof Element) {
        input =
          element.closest("input[type='file']") ||
          element.querySelector("input[type='file']") ||
          (element.parentElement ? element.parentElement.querySelector("input[type='file']") : null);
      }

      if (!input && selectorHint) {
        try {
          input = document.querySelector(`${rawTarget} input[type='file']`);
        } catch {
          input = null;
        }
      }

      const available = Array.from(document.querySelectorAll("input[type='file']")).map((node) => ({
        selector: buildSelector(node),
        accept: node.getAttribute("accept") || "",
      }));

      if (!input) {
        return {
          ok: false,
          error:
            available.length > 0
              ? `No matching input[type=file] for "${rawTarget}". File inputs on page: ${available.map((item) => `${item.selector || "input[type=file]"}${item.accept ? ` (accept=${item.accept})` : ""}`).join(", ")}`
              : `No matching input[type=file] for "${rawTarget}". No file inputs are present on the page.`,
        };
      }

      return {
        ok: true,
        selector: buildSelector(input),
        accept: input.getAttribute("accept") || "",
      };
    },
    [target],
  );
}

async function runOpen(params, context = {}) {
  const normalizedUrl = normalizeUrl(params.url);
  if (!normalizedUrl) {
    throw new Error("Missing required argument <url>.");
  }

  await loadState();
  const requestedTabId = await resolveTabParam(params);
  let tab;
  if (params.newTab) {
    if (params.newWindow || managedTabs.size === 0) {
      tab = await createManagedWindow(context);
      throwIfCancelled(context, "navigation");
      await chrome.tabs.update(tab.id, { url: normalizedUrl, active: true });
    } else {
      const sourceTab = await getManagedTab({ tabId: requestedTabId, allowFallback: false, requireScriptable: false });
      throwIfCancelled(context, "tab creation");
      tab = await chrome.tabs.create({
        url: normalizedUrl,
        active: true,
        ...(Number.isInteger(sourceTab.windowId) ? { windowId: sourceTab.windowId } : {}),
      });
      await addManagedTab(tab);
    }
  } else {
    tab = await getManagedTab({ tabId: requestedTabId, allowFallback: true, requireScriptable: false, context });
    throwIfCancelled(context, "navigation");
    await chrome.tabs.update(tab.id, { url: normalizedUrl, active: true });
  }

  await waitForTabComplete(tab.id, 10000, context);
  const updatedTab = await chrome.tabs.get(tab.id);
  await addManagedTab(updatedTab);
  clearSessionState(updatedTab.id);

  const waitSelector = typeof params.wait === "string" ? params.wait.trim() : "";
  if (waitSelector) {
    if (isRestrictedUrl(updatedTab.url || "")) {
      throw new Error(`Cannot apply --wait on restricted URL (${updatedTab.url || "unknown"}).`);
    }
    await waitForSelector(updatedTab.id, waitSelector, 10000, context);
  }

  const preview = await readPreview(updatedTab.id);
  await maybePostActionDelay(params);
  return preview;
}

async function runClick(params, context = {}) {
  const tabId = await resolveTabParam(params);
  const tab = await getManagedTab({ tabId, allowFallback: false, requireScriptable: true });
  const rawTarget = String(params.target || "").trim();
  const target = resolveTargetRef(tab.id, rawTarget);
  if (!target) {
    throw new Error("Missing required argument <target>.");
  }

  const index = Number.isFinite(params.index) ? Math.max(0, Number(params.index)) : 0;
  const textOnly = Boolean(params.text);
  const includeCoords = Boolean(params.coords);
  const { result, stateChanges } = await captureWriteStateChanges(tab.id, async () => {
    throwIfCancelled(context, "click");
    const clickResult = await runInTab(tab.id, (rawTargetValue, rawIndex, selectorHint, explicitTextOnly, wantCoords) => {
      const normalize = (value) => String(value || "").replace(/\s+/g, " ").trim();
      const isVisible = (node) => {
        if (!(node instanceof Element)) {
          return false;
        }
        const rect = node.getBoundingClientRect();
        const style = window.getComputedStyle(node);
        return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";
      };
      const describeNode = (node) => {
        if (!(node instanceof Element)) {
          return "element";
        }
        const tag = node.tagName.toLowerCase();
        if (node.id) {
          return `${tag}#${node.id}`;
        }
        if (node.classList.length > 0) {
          return `${tag}.${Array.from(node.classList).slice(0, 2).join(".")}`;
        }
        const dataE2e = node.getAttribute("data-e2e");
        if (dataE2e) {
          return `${tag}[data-e2e='${dataE2e}']`;
        }
        return tag;
      };
      const targetText = normalize(rawTargetValue).toLowerCase();
      const indexValue = Number.isFinite(rawIndex) ? rawIndex : 0;
      const candidateBuckets = [];

      let matches = [];
      if (selectorHint && !explicitTextOnly) {
        try {
          matches = Array.from(document.querySelectorAll(rawTargetValue));
        } catch {
          matches = [];
        }
      }

      if (matches.length === 0 && targetText) {
        const primaryCandidates = Array.from(
          document.querySelectorAll("a, button, input, textarea, select, label, summary, [role='button'], [role='link']"),
        ).filter(isVisible);
        candidateBuckets.push(...primaryCandidates);
        const exact = [];
        const partial = [];
        for (const node of primaryCandidates) {
          const text = normalize(node.innerText || node.textContent || node.getAttribute("aria-label") || node.getAttribute("value"));
          if (!text) {
            continue;
          }
          const lower = text.toLowerCase();
          if (lower === targetText) {
            exact.push(node);
          } else if (lower.includes(targetText)) {
            partial.push(node);
          }
        }
        matches = exact.length > 0 ? exact : partial;
      }

      if (matches.length === 0 && targetText) {
        const allVisible = Array.from(document.querySelectorAll("body *")).filter(isVisible);
        const scored = [];
        for (const node of allVisible) {
          const text = normalize(
            node.innerText ||
              node.textContent ||
              node.getAttribute("aria-label") ||
              node.getAttribute("data-e2e") ||
              node.getAttribute("value"),
          );
          if (!text) {
            continue;
          }
          const lower = text.toLowerCase();
          if (!lower.includes(targetText) && lower !== targetText) {
            continue;
          }
          const style = window.getComputedStyle(node);
          const clickableScore =
            (style.cursor === "pointer" ? 3 : 0) +
            (typeof node.onclick === "function" ? 3 : 0) +
            (node.hasAttribute("role") ? 2 : 0) +
            (node.hasAttribute("data-e2e") ? 2 : 0) +
            (node.hasAttribute("tabindex") ? 1 : 0);
          scored.push({
            node,
            clickableScore,
            exact: lower === targetText ? 1 : 0,
          });
        }
        scored.sort((left, right) => right.exact - left.exact || right.clickableScore - left.clickableScore);
        matches = scored.map((item) => item.node);
        candidateBuckets.push(...matches);
      }

      if (matches.length === 0) {
        const clickableSuggestions = Array.from(
          new Set(
            Array.from(document.querySelectorAll("button, a, [role='button'], [role='link'], [onclick], [data-e2e]"))
              .filter(isVisible)
              .map((node) => ({
                text: normalize(
                  node.innerText || node.textContent || node.getAttribute("aria-label") || node.getAttribute("data-e2e") || node.getAttribute("value"),
                ),
                desc: describeNode(node),
              }))
              .filter((item) => item.text)
              .slice(0, 8)
              .map((item) => `  "${item.text}" (${item.desc})`),
          ),
        );
        const similar = clickableSuggestions.find((item) => item.toLowerCase().includes(targetText));
        return {
          ok: false,
          error: `No element matching "${rawTargetValue}".\nVisible clickable elements on page:\n${clickableSuggestions.join("\n") || "  (none found)"}${similar ? `\nDid you mean ${similar.trim()}?` : ""}`,
        };
      }

      if (indexValue >= matches.length) {
        return {
          ok: false,
          error: `Match index ${indexValue} is out of range for "${rawTargetValue}" (${matches.length} matches).`,
        };
      }

      const element = matches[indexValue];
      if (!element) {
        return {
          ok: false,
          error: `No element matching "${rawTargetValue}".`,
        };
      }

      if (element instanceof HTMLElement) {
        element.scrollIntoView({ behavior: "auto", block: "center", inline: "center" });
        element.click();
      } else if (typeof element.click === "function") {
        element.click();
      }

      const rect = typeof element.getBoundingClientRect === "function" ? element.getBoundingClientRect() : null;
      return {
        ok: true,
        coords:
          wantCoords && rect
            ? { x: rect.x, y: rect.y, width: rect.width, height: rect.height }
            : undefined,
      };
    }, [target, index, isProbablySelector(target), textOnly, includeCoords]);

    await waitForTabComplete(tab.id, 2000, context).catch(() => undefined);
    return clickResult;
  });

  if (!result?.ok) {
    throw new Error(result?.error || `No element matching "${target}".`);
  }

  const preview = await readPreview(tab.id);
  await maybePostActionDelay(params);
  return {
    clicked: rawTarget,
    target,
    ...(result.coords ? { coords: result.coords } : {}),
    stateChanges,
    ...preview,
  };
}

async function runType(params, context = {}) {
  const tabId = await resolveTabParam(params);
  const tab = await getManagedTab({ tabId, allowFallback: false, requireScriptable: true });
  const rawTarget = String(params.target || "").trim();
  const target = resolveTargetRef(tab.id, rawTarget);
  if (!target) {
    throw new Error("Missing required argument <target>.");
  }
  if (typeof params.text !== "string") {
    throw new Error("Missing required argument <text>.");
  }

  const text = params.text;
  const index = Number.isFinite(params.index) ? Math.max(0, Number(params.index)) : 0;

  const { result, stateChanges } = await captureWriteStateChanges(tab.id, () => {
    throwIfCancelled(context, "typing");
    return runInTab(tab.id, (rawTarget, rawText, rawIndex, selectorHint) => {
      const normalize = (value) => String(value || "").replace(/\s+/g, " ").trim();
      const targetText = normalize(rawTarget).toLowerCase();
      const indexValue = Number.isFinite(rawIndex) ? rawIndex : 0;

      let matches = [];
      if (selectorHint) {
        try {
          matches = Array.from(document.querySelectorAll(rawTarget));
        } catch {
          matches = [];
        }
      }

      if (matches.length === 0 && targetText) {
        const candidates = Array.from(
          document.querySelectorAll("input, textarea, [contenteditable='true'], [role='textbox'], [aria-label], [name]"),
        );
        const exact = [];
        const partial = [];
        for (const node of candidates) {
          const textContent = normalize(
            node.innerText ||
              node.textContent ||
              node.getAttribute("aria-label") ||
              node.getAttribute("name") ||
              node.getAttribute("placeholder"),
          );
          if (!textContent) {
            continue;
          }
          const lower = textContent.toLowerCase();
          if (lower === targetText) {
            exact.push(node);
          } else if (lower.includes(targetText)) {
            partial.push(node);
          }
        }
        matches = exact.length > 0 ? exact : partial;
      }

      if (matches.length === 0) {
        const suggestions = Array.from(document.querySelectorAll("input, textarea, [contenteditable='true'], [role='textbox']"))
          .map((node) =>
            normalize(
              node.innerText ||
                node.textContent ||
                node.getAttribute("aria-label") ||
                node.getAttribute("name") ||
                node.getAttribute("placeholder"),
            ),
          )
          .filter(Boolean)
          .slice(0, 8);
        return {
          ok: false,
          error:
            suggestions.length > 0
              ? `No writable element matching "${rawTarget}". Available inputs: ${suggestions.map((item) => `"${item}"`).join(", ")}`
              : `No writable element matching "${rawTarget}".`,
        };
      }

      if (indexValue >= matches.length) {
        return {
          ok: false,
          error: `Match index ${indexValue} is out of range for "${rawTarget}" (${matches.length} matches).`,
        };
      }

      const element = matches[indexValue];

      if (element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement) {
        element.focus();
        element.value = "";
        element.dispatchEvent(new Event("input", { bubbles: true }));
        element.value = rawText;
        element.dispatchEvent(new Event("input", { bubbles: true }));
        element.dispatchEvent(new Event("change", { bubbles: true }));
        return { ok: true };
      }

      if (element instanceof HTMLElement && element.isContentEditable) {
        element.focus();
        element.textContent = rawText;
        element.dispatchEvent(new Event("input", { bubbles: true }));
        element.dispatchEvent(new Event("change", { bubbles: true }));
        return { ok: true };
      }

      return { ok: false, error: `Element "${rawTarget}" is not a writable input.` };
    }, [target, text, index, isProbablySelector(target)]);
  });

  if (!result?.ok) {
    throw new Error(result?.error || `No writable element matching "${target}".`);
  }

  await maybePostActionDelay(params);
  return {
    typedInto: rawTarget,
    target,
    text,
    stateChanges,
  };
}

async function runFill(params, context = {}) {
  const tabId = await resolveTabParam(params);
  const tab = await getManagedTab({ tabId, allowFallback: false, requireScriptable: true });
  const rawTarget = String(params.target || "").trim();
  const target = resolveTargetRef(tab.id, rawTarget);
  if (!target) {
    throw new Error("Missing required argument <target>.");
  }

  const text = typeof params.text === "string" ? params.text : "";
  const clear = Boolean(params.clear);
  const append = Boolean(params.append);
  const index = Number.isFinite(params.index) ? Math.max(0, Number(params.index)) : 0;

  const resolved = await resolveWritableTarget(tab.id, target, index);
  if (!resolved?.ok) {
    throw new Error(resolved?.error || `No writable element matching "${rawTarget}".`);
  }

  const previous = await readElementValue(tab.id, resolved.selector);
  const intended = clear ? "" : append ? `${previous}${text}` : text;
  const { stateChanges } = await captureWriteStateChanges(tab.id, async () => {
    throwIfCancelled(context, "fill");
    await runInTab(tab.id, (selector) => {
      const element = selector ? document.querySelector(selector) : null;
      if (element instanceof HTMLElement) {
        element.scrollIntoView({ behavior: "auto", block: "center", inline: "center" });
        element.focus();
        element.click();
      }
    }, [resolved.selector]);
    throwIfCancelled(context, "fill input dispatch");
    await withDebugger(tab.id, async (debugTarget) => {
      const modifiers = await getPlatformModifier();
      if (!append) {
        throwIfCancelled(context, "fill selection");
        await dispatchShortcut(debugTarget, {
          key: "a",
          code: "KeyA",
          windowsVirtualKeyCode: 65,
          modifiers,
        });
        throwIfCancelled(context, "fill deletion");
        await dispatchBackspace(debugTarget);
      }

      if (!clear) {
        for (const character of Array.from(text)) {
          throwIfCancelled(context, "fill character dispatch");
          await dispatchCharacter(debugTarget, character);
        }
      }
    });
  });

  const actual = await readElementValue(tab.id, resolved.selector);
  await maybePostActionDelay(params);
  return {
    filledInto: rawTarget,
    target: resolved.selector || target,
    intended,
    actual,
    match: actual === intended,
    stateChanges,
  };
}

async function runUpload(params, context = {}) {
  const tabId = await resolveTabParam(params);
  const tab = await getManagedTab({ tabId, allowFallback: false, requireScriptable: true });
  const rawTarget = String(params.target || "").trim();
  const target = resolveTargetRef(tab.id, rawTarget);
  const filepath = String(params.filepath || "").trim();
  if (!target) {
    throw new Error("Missing required argument <target>.");
  }
  if (!filepath) {
    throw new Error("Missing required argument <filepath>.");
  }
  const resolved = await resolveUploadTarget(tab.id, target);
  if (!resolved?.ok || !resolved.selector) {
    throw new Error(resolved?.error || `No matching input[type=file] for "${rawTarget}".`);
  }

  const { stateChanges } = await captureWriteStateChanges(tab.id, async () => {
    throwIfCancelled(context, "file upload");
    await withDebugger(tab.id, async (debugTarget) => {
      const documentNode = await chrome.debugger.sendCommand(debugTarget, "DOM.getDocument", { depth: -1, pierce: true });
      const rootNodeId = documentNode?.root?.nodeId;
      if (!rootNodeId) {
        throw new Error("Unable to resolve DOM document for upload.");
      }
      const query = await chrome.debugger.sendCommand(debugTarget, "DOM.querySelector", {
        nodeId: rootNodeId,
        selector: resolved.selector,
      });
      const nodeId = query?.nodeId;
      if (!nodeId) {
        throw new Error(`Resolved upload selector no longer matches: ${resolved.selector}`);
      }
      throwIfCancelled(context, "file selection");
      await chrome.debugger.sendCommand(debugTarget, "DOM.setFileInputFiles", {
        files: [filepath],
        nodeId,
      });
    });
  });

  const preview = await readPreview(tab.id);
  await maybePostActionDelay(params);
  return {
    uploaded: filepath,
    target: rawTarget,
    selector: resolved.selector,
    stateChanges,
    ...preview,
  };
}

function parseDelayRange(value) {
  const raw = String(value || "").trim();
  if (!raw) {
    return null;
  }
  const rangeMatch = raw.match(/^(\d+)\s*-\s*(\d+)$/);
  if (rangeMatch) {
    const min = Number.parseInt(rangeMatch[1], 10);
    const max = Number.parseInt(rangeMatch[2], 10);
    if (Number.isFinite(min) && Number.isFinite(max) && min >= 0 && max >= min) {
      return { min, max };
    }
    throw new Error(`Invalid --ms range "${raw}". Use min-max in milliseconds.`);
  }
  const fixed = Number.parseInt(raw, 10);
  if (Number.isFinite(fixed) && fixed >= 0) {
    return { min: fixed, max: fixed };
  }
  throw new Error(`Invalid --ms value "${raw}". Use a number or min-max range.`);
}

async function currentWaitContext(tabId) {
  const preview = await readPreview(tabId);
  return `${preview.title || "(untitled)"} @ ${preview.url} :: ${(preview.preview || "").slice(0, 200)}`;
}

async function runWait(params, context = {}) {
  const tabId = await resolveTabParam(params);
  const tab = await getManagedTab({ tabId, allowFallback: false, requireScriptable: true });
  const selector = typeof params.selector === "string" && params.selector ? resolveTargetRef(tab.id, params.selector) : null;
  const text = typeof params.text === "string" && params.text ? params.text : null;
  const gone = typeof params.gone === "string" && params.gone ? resolveTargetRef(tab.id, params.gone) : null;
  const stable = typeof params.stable === "string" && params.stable ? resolveTargetRef(tab.id, params.stable) : null;
  const ms = typeof params.ms === "string" && params.ms ? params.ms : null;
  const timeoutMs = Number.isFinite(params.timeout) ? Math.max(0, Number(params.timeout)) : 15000;

  if (ms) {
    const range = parseDelayRange(ms);
    const delay = range.min === range.max ? range.min : Math.floor(Math.random() * (range.max - range.min + 1)) + range.min;
    await cancellableSleep(delay, context);
    const preview = await readPreview(tab.id);
    return {
      waitedMs: delay,
      condition: "delay",
      ...preview,
    };
  }

  const deadline = Date.now() + timeoutMs;
  let lastStableValue = "";
  let stableSince = 0;

  while (Date.now() < deadline) {
    throwIfCancelled(context, "wait completed");
    const result = await runInTab(
      tab.id,
      (targetSelector, targetText, goneSelector, stableSelector) => {
        const isVisible = (node) => {
          if (!(node instanceof Element)) {
            return false;
          }
          const rect = node.getBoundingClientRect();
          const style = window.getComputedStyle(node);
          return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";
        };

        if (targetSelector) {
          let node = null;
          try {
            node = document.querySelector(targetSelector);
          } catch {
            return { ok: false, mode: "selector", value: null };
          }
          return { ok: Boolean(node && isVisible(node)), mode: "selector", value: null };
        }

        if (targetText) {
          return {
            ok: (document.body?.innerText || "").includes(targetText),
            mode: "text",
            value: null,
          };
        }

        if (goneSelector) {
          let node = null;
          try {
            node = document.querySelector(goneSelector);
          } catch {
            return { ok: true, mode: "gone", value: null };
          }
          return { ok: !node || !isVisible(node), mode: "gone", value: null };
        }

        if (stableSelector) {
          let node = null;
          try {
            node = document.querySelector(stableSelector);
          } catch {
            return { ok: false, mode: "stable", value: "" };
          }
          if (!node) {
            return { ok: false, mode: "stable", value: "" };
          }
          const rect = node.getBoundingClientRect();
          const style = window.getComputedStyle(node);
          const formState = Array.from(node.matches("input, textarea, select, option, details") ? [node] : [])
            .concat(Array.from(node.querySelectorAll("input, textarea, select, option, details")))
            .map((element) => ({
              value: "value" in element ? element.value : undefined,
              checked: "checked" in element ? element.checked : undefined,
              selected: "selected" in element ? element.selected : undefined,
              open: "open" in element ? element.open : undefined,
              disabled: "disabled" in element ? element.disabled : undefined,
            }));
          const value = JSON.stringify({
            html: node.outerHTML,
            text: node.innerText || node.textContent || "",
            rect: [rect.x, rect.y, rect.width, rect.height],
            layout: [node.scrollWidth, node.scrollHeight, node.scrollLeft, node.scrollTop],
            style: [style.display, style.visibility, style.opacity, style.position],
            formState,
          });
          return { ok: true, mode: "stable", value };
        }

        return { ok: false, mode: "unknown", value: null };
      },
      [selector, text, gone, stable],
    );

    if (result?.mode === "stable") {
      if (!result.ok) {
        await cancellableSleep(200, context);
        continue;
      }
      if (result.value === lastStableValue) {
        if (!stableSince) {
          stableSince = Date.now();
        }
        if (Date.now() - stableSince >= 500) {
          const preview = await readPreview(tab.id);
          return {
            waitedFor: stable,
            condition: "stable",
            ...preview,
          };
        }
      } else {
        lastStableValue = result.value;
        stableSince = Date.now();
      }
    } else if (result?.ok) {
      const preview = await readPreview(tab.id);
      return {
        waitedFor: selector || text || gone,
        condition: result.mode,
        ...preview,
      };
    }

    await cancellableSleep(200, context);
  }

  throwIfCancelled(context, "wait completed");
  const waitContext = await currentWaitContext(tab.id);
  const waitedFor = selector ? `selector "${selector}"` : text ? `text "${text}"` : gone ? `gone "${gone}"` : `stable "${stable}"`;
  throw new Error(`Timed out waiting for ${waitedFor}. Current page state: ${waitContext}`);
}

async function runSnapshot(params) {
  const depth = Number.isFinite(params.depth) ? Number(params.depth) : -1;
  const tabId = await resolveTabParam(params);
  const tab = await getManagedTab({ tabId, allowFallback: false, requireScriptable: true });
  const scope = typeof params.scope === "string" && params.scope ? resolveTargetRef(tab.id, params.scope) : null;
  const snapshot = await captureAxTree(tab.id, { scope, depth });
  getTabState(tab.id).snapshotBaseline = snapshot;
  const preview = await readPreview(tab.id);
  return {
    snapshot: snapshot.snapshot,
    ...preview,
  };
}

async function runDiff(params) {
  const depth = Number.isFinite(params.depth) ? Number(params.depth) : -1;
  const tabId = await resolveTabParam(params);
  const tab = await getManagedTab({ tabId, allowFallback: false, requireScriptable: true });
  const scope = typeof params.scope === "string" && params.scope ? resolveTargetRef(tab.id, params.scope) : null;
  const tabState = getTabState(tab.id);
  const current = await captureAxTree(tab.id, { scope, depth });
  const previous = tabState.snapshotBaseline;
  tabState.snapshotBaseline = current;
  const preview = await readPreview(tab.id);

  if (!previous) {
    return {
      diff: current.snapshot,
      mode: "full",
      ...preview,
    };
  }

  const previousMap = new Map(previous.entries.map((entry) => [entry.key, entry]));
  const currentMap = new Map(current.entries.map((entry) => [entry.key, entry]));
  const lines = [];

  for (const [key, nextEntry] of currentMap.entries()) {
    const prevEntry = previousMap.get(key);
    if (!prevEntry) {
      lines.push(`ADDED: ${nextEntry.state}`);
      continue;
    }
    if (prevEntry.state !== nextEntry.state) {
      lines.push(`CHANGED: ${prevEntry.state} -> ${nextEntry.state}`);
    }
  }

  for (const [key, prevEntry] of previousMap.entries()) {
    if (!currentMap.has(key)) {
      lines.push(`REMOVED: ${prevEntry.state}`);
    }
  }

  return {
    diff: lines.join("\n") || "No changes since last snapshot.",
    mode: "diff",
    ...preview,
  };
}

async function runInspect(params) {
  const tabId = await resolveTabParam(params);
  const tab = await getManagedTab({ tabId, allowFallback: false, requireScriptable: true });
  const scope = typeof params.scope === "string" && params.scope ? resolveTargetRef(tab.id, params.scope) : null;
  const includeHidden = Boolean(params.all);
  const includeCoords = Boolean(params.coords);
  const inspected = await runInTab(
    tab.id,
    (scopeSelector, allElements, wantCoords) => {
      const cssEscape = (value) => (window.CSS && typeof window.CSS.escape === "function" ? window.CSS.escape(value) : value);
      const normalize = (value) => String(value || "").replace(/\s+/g, " ").trim();
      const root = scopeSelector ? document.querySelector(scopeSelector) : document;
      if (!root) {
        return { error: `No element matches scope selector "${scopeSelector}".`, elements: [] };
      }

      const isVisible = (node) => {
        if (!(node instanceof Element)) {
          return false;
        }
        const rect = node.getBoundingClientRect();
        const style = window.getComputedStyle(node);
        return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";
      };

      const selectorFor = (element) => {
        if (!(element instanceof Element)) {
          return null;
        }
        if (element.id) {
          return `#${cssEscape(element.id)}`;
        }
        for (const attr of ["data-e2e", "data-testid", "name", "aria-label", "placeholder", "href", "accept"]) {
          const value = element.getAttribute(attr);
          if (value && document.querySelectorAll(`${element.tagName.toLowerCase()}[${attr}="${cssEscape(value)}"]`).length === 1) {
            return `${element.tagName.toLowerCase()}[${attr}="${cssEscape(value)}"]`;
          }
        }
        const parts = [];
        let current = element;
        while (current && current instanceof Element && current !== document.body) {
          let part = current.tagName.toLowerCase();
          if (current.classList.length > 0) {
            part += `.${Array.from(current.classList)
              .slice(0, 2)
              .map((value) => cssEscape(value))
              .join(".")}`;
          }
          const siblings = current.parentElement
            ? Array.from(current.parentElement.children).filter((child) => child.tagName === current.tagName)
            : [];
          if (siblings.length > 1) {
            part += `:nth-of-type(${siblings.indexOf(current) + 1})`;
          }
          parts.unshift(part);
          const selector = parts.join(" > ");
          if (document.querySelectorAll(selector).length === 1) {
            return selector;
          }
          current = current.parentElement;
        }
        return parts.join(" > ") || element.tagName.toLowerCase();
      };

      const candidates = Array.from(
        root.querySelectorAll(
          "input, textarea, select, button, [role], [contenteditable], a[href], [onclick], [data-e2e], summary",
        ),
      );

      const elements = [];
      for (const element of candidates) {
        if (!(element instanceof HTMLElement || element instanceof SVGElement)) {
          continue;
        }
        if (!allElements && !isVisible(element)) {
          continue;
        }
        const tag = element.tagName.toLowerCase();
        const role = element.getAttribute("role") || (tag === "a" ? "link" : tag === "button" ? "button" : tag);
        const text = normalize(element.innerText || element.textContent);
        const label = normalize(
          element.getAttribute("aria-label") ||
            element.getAttribute("name") ||
            element.getAttribute("placeholder") ||
            (element.labels && element.labels[0] ? element.labels[0].innerText || element.labels[0].textContent : ""),
        );
        const rect = typeof element.getBoundingClientRect === "function" ? element.getBoundingClientRect() : null;
        elements.push({
          tag,
          role,
          type: element instanceof HTMLInputElement ? element.type : undefined,
          text: text || undefined,
          label: label || undefined,
          checked: element instanceof HTMLInputElement && /checkbox|radio/.test(element.type) ? element.checked : undefined,
          enabled: !(element instanceof HTMLInputElement || element instanceof HTMLButtonElement || element instanceof HTMLSelectElement || element instanceof HTMLTextAreaElement)
            ? element.getAttribute("aria-disabled") !== "true"
            : !element.disabled,
          visible: isVisible(element),
          contenteditable: element instanceof HTMLElement ? element.isContentEditable || undefined : undefined,
          accept: element instanceof HTMLInputElement && element.type === "file" ? element.accept || undefined : undefined,
          selector: selectorFor(element),
          coords:
            rect && wantCoords
              ? { x: rect.x, y: rect.y, width: rect.width, height: rect.height }
              : undefined,
          charCount: text ? text.length : undefined,
        });
      }

      return { elements };
    },
    [scope, includeHidden, includeCoords],
  );

  if (inspected?.error) {
    throw new Error(inspected.error);
  }

  clearRefMap(tab.id);
  const elements = Array.isArray(inspected?.elements) ? inspected.elements : [];
  const preview = await readPreview(tab.id);
  const tabState = getTabState(tab.id);
  const withRefs = elements.map((element) => {
    const ref = `e${tabState.nextRefId++}`;
    if (element.selector) {
      tabState.refMap[ref] = element.selector;
    }
    return {
      ref,
      ...element,
    };
  });

  return {
    url: preview.url,
    title: preview.title,
    elements: withRefs,
  };
}

async function runExtract(params) {
  const tabId = await resolveTabParam(params);
  const tab = await getManagedTab({ tabId, allowFallback: false, requireScriptable: true });
  const selector = typeof params.selector === "string" && params.selector ? resolveTargetRef(tab.id, params.selector) : null;
  const scope = typeof params.scope === "string" && params.scope ? resolveTargetRef(tab.id, params.scope) : null;
  const asJson = Boolean(params.json);
  const rawLimit = Number(params.limit);
  const limit = Number.isFinite(rawLimit) && rawLimit > 0 ? rawLimit : 20;
  const result = await runInTab(
    tab.id,
    (targetSelector, scopeSelector, outputJson, itemLimit) => {
      const normalize = (value) => String(value || "").replace(/\s+/g, " ").trim();
      const root = scopeSelector ? document.querySelector(scopeSelector) : document;
      if (!root) {
        return outputJson ? [] : "";
      }

      if (!targetSelector) {
        if (outputJson) {
          return Array.from(root.querySelectorAll("a[href]"))
            .map((anchor) => ({
              text: normalize(anchor.innerText || anchor.textContent),
              href: anchor.href || null,
            }))
            .filter((item) => item.text)
            .slice(0, itemLimit);
        }

        return ((root === document ? document.body?.innerText : root.innerText) || "")
          .split("\n")
          .map((line) => line.trim())
          .filter(Boolean)
          .slice(0, itemLimit)
          .join("\n");
      }

      let nodes = [];
      try {
        nodes = Array.from(root.querySelectorAll(targetSelector));
      } catch {
        return { error: `Invalid selector "${targetSelector}".` };
      }

      if (nodes.length === 0) {
        const alternatives = Array.from(root.querySelectorAll("[id], [class], [role], main, form, section, article"))
          .slice(0, 8)
          .map((node) => {
            const tag = node.tagName.toLowerCase();
            if (node.id) {
              return `${tag}#${node.id}`;
            }
            if (node.classList.length > 0) {
              return `${tag}.${Array.from(node.classList).slice(0, 2).join(".")}`;
            }
            const role = node.getAttribute("role");
            if (role) {
              return `${tag}[role="${role}"]`;
            }
            return tag;
          });
        return {
          error: `No elements match selector "${targetSelector}". Nearby selectors: ${alternatives.join(", ") || "(none found)"}`,
        };
      }

      if (outputJson) {
        return nodes
          .map((node) => {
            const anchor = node instanceof HTMLAnchorElement ? node : node.querySelector("a[href]");
            return {
              text: normalize(node.innerText || node.textContent),
              href: anchor?.href || null,
            };
          })
          .filter((item) => item.text)
          .slice(0, itemLimit);
      }

      return nodes
        .map((node) => normalize(node.innerText || node.textContent))
        .filter(Boolean)
        .slice(0, itemLimit)
        .join("\n");
    },
    [selector, scope, asJson, limit],
  );
  if (result?.error) {
    throw new Error(result.error);
  }
  return result;
}

async function runHtml(params) {
  const tabId = await resolveTabParam(params);
  const tab = await getManagedTab({ tabId, allowFallback: false, requireScriptable: true });
  const selector = typeof params.selector === "string" && params.selector ? resolveTargetRef(tab.id, params.selector) : null;
  const rawLimit = Number(params.limit);
  const limit = Number.isFinite(rawLimit) && rawLimit > 0 ? rawLimit : 120;

  return runInTab(
    tab.id,
    (targetSelector, lineLimit) => {
      const root = targetSelector ? document.querySelector(targetSelector) : document.documentElement;
      if (!root) {
        return "";
      }

      const clone = root.cloneNode(true);
      if (!(clone instanceof Element)) {
        return "";
      }

      for (const node of clone.querySelectorAll("script, style, noscript")) {
        node.remove();
      }

      return clone.outerHTML
        .replace(/>\s+</g, ">\n<")
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean)
        .slice(0, lineLimit)
        .join("\n");
    },
    [selector, limit],
  );
}

async function evaluateViaDebugger(tabId, expression) {
  return withDebugger(tabId, async (target) => {
    const frameTree = await chrome.debugger.sendCommand(target, "Page.getFrameTree");
    const frameId = frameTree?.frameTree?.frame?.id;
    if (!frameId) {
      throw new Error("Unable to resolve frame id for evaluation.");
    }

    const isolatedWorld = await chrome.debugger.sendCommand(target, "Page.createIsolatedWorld", {
      frameId,
      worldName: "browserCliV2Eval",
      grantUniveralAccess: true,
    });
    const contextId = isolatedWorld?.executionContextId;
    if (!contextId) {
      throw new Error("Unable to create isolated world for evaluation.");
    }

    const evaluation = await chrome.debugger.sendCommand(target, "Runtime.evaluate", {
      expression,
      awaitPromise: true,
      returnByValue: true,
      userGesture: true,
      allowUnsafeEvalBlockedByCSP: true,
      contextId,
    });

    if (evaluation?.exceptionDetails) {
      const message =
        evaluation.exceptionDetails.text ||
        evaluation.result?.description ||
        evaluation.result?.value ||
        "Evaluation failed.";
      throw new Error(String(message));
    }

    const result = evaluation?.result;
    if (!result) {
      return null;
    }

    if (Object.prototype.hasOwnProperty.call(result, "value")) {
      return result.value;
    }

    if (typeof result.unserializableValue === "string") {
      return result.unserializableValue;
    }

    return result.description ?? null;
  });
}

async function runEval(params) {
  const expression = String(params.expression || "").trim();
  if (!expression) {
    throw new Error("Missing required argument <js>.");
  }

  const tabId = await resolveTabParam(params);
  const tab = await getManagedTab({ tabId, allowFallback: false, requireScriptable: false });
  return evaluateViaDebugger(tab.id, expression);
}

async function runDialog(params, context = {}) {
  const accept = params.accept;
  const dismiss = Boolean(params.dismiss);
  const tabId = await resolveTabParam(params);
  const tab = await getManagedTab({ tabId, allowFallback: false, requireScriptable: false });
  const tabState = getTabState(tab.id);

  if (accept || dismiss) {
    if (!tabState.dialog?.open) {
      throw new Error("No browser dialog is currently recorded as open.");
    }

    const target = { tabId: tab.id };
    throwIfCancelled(context, "dialog handling");
    await debuggerPool.forceDetach(tab.id).catch(() => undefined);
    try {
      await chrome.debugger.attach(target, "1.3");
      throwIfCancelled(context, "dialog handling");
      await chrome.debugger.sendCommand(target, "Page.handleJavaScriptDialog", {
        accept: Boolean(accept) && !dismiss,
        promptText: typeof accept === "string" ? accept : "",
      });
    } catch (error) {
      throw new Error(`Failed to handle browser dialog: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      try {
        await chrome.debugger.detach(target);
      } catch {
        // Ignore detach failures after dialog handling.
      }
    }
    const handled = tabState.dialog;
    tabState.dialog = null;
    return {
      handled: dismiss ? "dismissed" : "accepted",
      type: handled?.type || "dialog",
      message: handled?.message || "",
      url: tab.url || "about:blank",
      title: tab.title || "",
    };
  }

  return {
    open: Boolean(tabState.dialog?.open),
    ...(tabState.dialog || {}),
    url: tab.url || "about:blank",
    title: tab.title || "",
  };
}

async function runTabs() {
  await loadState();
  const entries = await Promise.all(
    Array.from(managedTabs.keys()).map(async (tabId) => {
      try {
        const tab = await chrome.tabs.get(tabId);
        await updateManagedTab(tab);
        const entry = getManagedTabEntry(tabId);
        return entry
          ? {
              alias: entry.alias,
              tabId: entry.tabId,
              url: tab.url || entry.url,
              title: tab.title || entry.title,
              active: tab.id === activeTabId,
            }
          : null;
      } catch {
        await removeManagedTab(tabId);
        return null;
      }
    }),
  );

  return entries.filter(Boolean);
}

async function runFocus(params, context = {}) {
  const tabId = await resolveTabParam(params);
  const tab = await getManagedTab({ tabId, allowFallback: false, requireScriptable: false });
  throwIfCancelled(context, "window focus");
  await chrome.windows.update(tab.windowId, { focused: true }).catch(() => undefined);
  throwIfCancelled(context, "tab focus");
  await chrome.tabs.update(tab.id, { active: true }).catch(() => undefined);
  const updatedTab = await chrome.tabs.get(tab.id);
  await addManagedTab(updatedTab);
  return {
    alias: getManagedTabEntry(updatedTab.id)?.alias || null,
    tabId: updatedTab.id,
    url: updatedTab.url || "about:blank",
    title: updatedTab.title || "",
    active: true,
  };
}

async function runClose(params, context = {}) {
  const tabId = await resolveTabParam(params);
  const tab = await getManagedTab({ tabId, allowFallback: false, requireScriptable: false });
  const entry = getManagedTabEntry(tab.id);
  const closed = {
    alias: entry?.alias || null,
    tabId: tab.id,
    url: tab.url || "about:blank",
    title: tab.title || "",
  };

  if (context.shouldContinue && !context.shouldContinue()) {
    throw new Error("Command cancelled before tab removal.");
  }

  beginStateMutationBatch();
  try {
    await chrome.tabs.remove(tab.id);
    await removeManagedTab(tab.id);
  } finally {
    await endStateMutationBatch();
  }
  return closed;
}

async function runCloseIdle(params, context = {}) {
  beginStateMutationBatch();
  try {
    const result = await closeIdleTabs({
      chromeApi: chrome,
      hours: params.hours,
      dryRun: Boolean(params.dryRun),
      shouldContinue: context.shouldContinue,
    });
    await removeManagedTabs(result.closed.map((tab) => tab.id));
    return result;
  } finally {
    await endStateMutationBatch();
  }
}

async function runStatus(params = {}) {
  await loadState();

  const hasExplicitTab =
    params.tabId != null && !(typeof params.tabId === "string" && !params.tabId.trim()) ||
    params.alias != null && !(typeof params.alias === "string" && !params.alias.trim());
  const requestedTabId = hasExplicitTab ? await resolveTabParam(params) : activeTabId;
  let managedTab = null;
  let activeManagedTab = null;
  const resolvedActiveTabId = activeTabId;

  if (requestedTabId != null) {
    const lookup = getManagedTab({ tabId: requestedTabId, allowFallback: false, requireScriptable: false });
    managedTab = hasExplicitTab ? await lookup : await lookup.catch(() => null);
  }

  if (resolvedActiveTabId != null) {
    activeManagedTab = await getManagedTab({ tabId: resolvedActiveTabId, allowFallback: false, requireScriptable: false }).catch(() => null);
  }

  const activeTab = await getActiveTab().catch(() => null);
  const tab = hasExplicitTab ? managedTab : managedTab || activeManagedTab || activeTab;
  const managedEntry = tab?.id != null ? getManagedTabEntry(tab.id) : null;
  const activeEntry = activeManagedTab?.id != null ? getManagedTabEntry(activeManagedTab.id) : null;

  return {
    url: tab?.url || "about:blank",
    title: tab?.title || "",
    tabId: tab?.id ?? null,
    managedTabId: managedTab?.id ?? activeManagedTab?.id ?? null,
    managedWindowId: managedTab?.windowId ?? activeManagedTab?.windowId ?? null,
    activeTabId: activeTab?.id ?? null,
    activeManagedTabId: activeManagedTab?.id ?? null,
    managedAlias: managedEntry?.alias ?? null,
    activeManagedAlias: activeEntry?.alias ?? null,
    managedTabs: listManagedTabs(),
    usingManagedTab: Boolean(managedTab || activeManagedTab),
  };
}

async function captureFullPage(tabId) {
  return withDebugger(tabId, async (target) => {
    const metrics = await chrome.debugger.sendCommand(target, "Page.getLayoutMetrics");
    const contentSize = metrics?.cssContentSize || metrics?.contentSize;

    let width = Math.ceil(Number(contentSize?.width || 0));
    let height = Math.ceil(Number(contentSize?.height || 0));
    if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
      throw new Error("Unable to determine page dimensions for full-page screenshot.");
    }

    width = Math.max(1, Math.min(width, MAX_FULL_PAGE_DIMENSION));
    height = Math.max(1, Math.min(height, MAX_FULL_PAGE_DIMENSION));

    const captured = await chrome.debugger.sendCommand(target, "Page.captureScreenshot", {
      format: "png",
      fromSurface: true,
      captureBeyondViewport: true,
      clip: {
        x: 0,
        y: 0,
        width,
        height,
        scale: 1,
      },
    });

    if (!captured?.data) {
      throw new Error("Full-page screenshot returned no image data.");
    }

    return {
      dataUrl: `data:image/png;base64,${captured.data}`,
      mode: "full-page",
    };
  });
}

async function captureViewportViaDebugger(tabId, format = "png", quality = 80) {
  return withDebugger(tabId, async (target) => {
    const normalizedFormat = format === "jpeg" ? "jpeg" : "png";
    const captured = await chrome.debugger.sendCommand(target, "Page.captureScreenshot", {
      format: normalizedFormat,
      fromSurface: true,
      ...(normalizedFormat === "jpeg" ? { quality } : {}),
    });
    if (!captured?.data) {
      throw new Error("Viewport screenshot returned no image data.");
    }
    return `data:image/${normalizedFormat};base64,${captured.data}`;
  });
}

async function dataUrlToBlob(dataUrl) {
  const match = /^data:([^;,]+)?(?:;charset=[^;,]+)?(;base64)?,(.*)$/s.exec(dataUrl);
  if (!match) {
    throw new Error("Invalid data URL.");
  }

  const mimeType = match[1] || "application/octet-stream";
  const isBase64 = Boolean(match[2]);
  const payload = match[3] || "";
  const bytesString = isBase64 ? atob(payload) : decodeURIComponent(payload);
  const bytes = new Uint8Array(bytesString.length);

  for (let index = 0; index < bytesString.length; index += 1) {
    bytes[index] = bytesString.charCodeAt(index);
  }

  return new Blob([bytes], { type: mimeType });
}

async function blobToDataUrl(blob) {
  const buffer = await blob.arrayBuffer();
  const bytes = new Uint8Array(buffer);
  let binary = "";
  const chunkSize = 0x8000;

  for (let index = 0; index < bytes.length; index += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(index, index + chunkSize));
  }

  return `data:${blob.type || "application/octet-stream"};base64,${btoa(binary)}`;
}

async function resizeCapturedImage(dataUrl, maxWidth, format, quality) {
  const targetWidth = Number.isFinite(maxWidth) ? Math.max(1, Math.floor(maxWidth)) : 0;
  if (!targetWidth) {
    return dataUrl;
  }

  const blob = await dataUrlToBlob(dataUrl);
  const bitmap = await createImageBitmap(blob);

  try {
    if (bitmap.width <= targetWidth) {
      return dataUrl;
    }

    const scale = targetWidth / bitmap.width;
    const width = targetWidth;
    const height = Math.max(1, Math.round(bitmap.height * scale));
    const canvas = new OffscreenCanvas(width, height);
    const context = canvas.getContext("2d");
    if (!context) {
      throw new Error("Failed to create offscreen canvas context.");
    }

    context.drawImage(bitmap, 0, 0, width, height);

    const normalizedFormat = format === "png" ? "image/png" : "image/jpeg";
    const blobQuality = Math.max(0, Math.min(1, (Number.isFinite(quality) ? quality : 80) / 100));
    const resized = await canvas.convertToBlob({
      type: normalizedFormat,
      quality: blobQuality,
    });

    return blobToDataUrl(resized);
  } finally {
    bitmap.close();
  }
}

async function runScreenshot(params = {}) {
  const tabId = await resolveTabParam(params);
  const tab = await getManagedTab({ tabId, allowFallback: false, requireScriptable: false });
  const url = tab.url || "about:blank";
  const title = tab.title || "";
  const useCompressedCapture = params.maxWidth != null || params.format != null;

  if (useCompressedCapture) {
    const quality = Number.isFinite(params.quality) ? Math.max(0, Math.min(100, Number(params.quality))) : 80;
    const format = params.format === "png" ? "png" : "jpeg";
    const captured = await captureTargetViaCdp({
      tabId: tab.id,
      fullPage: false,
      format,
      quality,
      captureFullPage,
      captureViewport: captureViewportViaDebugger,
    });
    const dataUrl = await resizeCapturedImage(captured.dataUrl, params.maxWidth, format, quality);

    return {
      dataUrl,
      mode: params.maxWidth != null ? "viewport-resized" : captured.mode,
      tabId: tab.id,
      url,
      title,
    };
  }

  const captured = await captureTargetViaCdp({
    tabId: tab.id,
    fullPage: true,
    captureFullPage,
    captureViewport: captureViewportViaDebugger,
  });
  return {
    ...captured,
    tabId: tab.id,
    url,
    title,
  };
}

async function dispatchAction(action, params, context = {}) {
  switch (action) {
    case "open":
      return runOpen(params, context);
    case "tabs":
      return runTabs();
    case "focus":
      return runFocus(params, context);
    case "close":
      return runClose(params, context);
    case "close-idle":
      return runCloseIdle(params, context);
    case "click":
      return runClick(params, context);
    case "type":
      return runType(params, context);
    case "fill":
      return runFill(params, context);
    case "upload":
      return runUpload(params, context);
    case "wait":
      return runWait(params, context);
    case "snapshot":
      return runSnapshot(params);
    case "diff":
      return runDiff(params);
    case "inspect":
      return runInspect(params);
    case "extract":
      return runExtract(params);
    case "screenshot":
      return runScreenshot(params);
    case "html":
      return runHtml(params);
    case "eval":
      return runEval(params);
    case "dialog":
      return runDialog(params, context);
    case "status":
      return runStatus(params);
    default:
      throw new Error(`Unknown action "${action}".`);
  }
}

function handleBridgeMessage(sourceSocket, rawData) {
  let payload;
  try {
    payload = JSON.parse(String(rawData));
  } catch {
    return;
  }

  const id = typeof payload?.id === "string" ? payload.id : "";
  if (!id) {
    return;
  }

  const cancelledRequests = cancelledRequestsBySocket.get(sourceSocket) ?? new Set();
  cancelledRequestsBySocket.set(sourceSocket, cancelledRequests);
  if (payload?.type === "cancel") {
    // Cancellation is recorded synchronously instead of waiting behind the
    // command queue. Queued destructive requests therefore expire safely.
    cancelledRequests.add(id);
    return;
  }

  void requestQueue.enqueue(() => handleRequest(payload, sourceSocket));
}

async function handleRequest(payload, responseSocket) {
  const id = typeof payload?.id === "string" ? payload.id : "";
  const action = typeof payload?.action === "string" ? payload.action : "";
  const params = payload?.params && typeof payload.params === "object" ? payload.params : {};
  const deadline = Number.isFinite(payload?.deadline) ? payload.deadline : Number.POSITIVE_INFINITY;
  const cancelledRequests = cancelledRequestsBySocket.get(responseSocket) ?? new Set();
  cancelledRequestsBySocket.set(responseSocket, cancelledRequests);
  const shouldContinue = () =>
    !cancelledRequests.has(id) && responseSocket.readyState === WebSocket.OPEN && Date.now() <= deadline;

  if (!id || !action || !shouldContinue()) {
    cancelledRequests.delete(id);
    return;
  }

  try {
    const data = await dispatchAction(action, params, { shouldContinue });
    if (shouldContinue()) {
      sendTo(responseSocket, { id, ok: true, data });
    }
  } catch (error) {
    if (!shouldContinue()) {
      return;
    }
    const baseError = error instanceof Error ? error.message : String(error);
    const targetTabId = await resolveTabParam(params).catch(() => null);
    const dialog = targetTabId != null ? getTabState(targetTabId).dialog : null;
    const dialogSuffix =
      action !== "dialog" && dialog?.open
        ? ` Dialog open: [${dialog.type}] "${dialog.message}". Use browser dialog --accept or --dismiss.`
        : "";
    sendTo(responseSocket, {
      id,
      ok: false,
      error: `${baseError}${dialogSuffix}`,
    });
  } finally {
    cancelledRequests.delete(id);
  }
}

chrome.tabs.onRemoved.addListener((tabId) => {
  void removeManagedTab(tabId);
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  void (async () => {
    await loadState();
    if (!managedTabs.has(tabId)) {
      return;
    }
    const mergedTab = {
      ...tab,
      id: tabId,
      windowId: Number.isInteger(tab.windowId) ? tab.windowId : getManagedTabEntry(tabId)?.windowId ?? null,
      url: typeof changeInfo.url === "string" ? changeInfo.url : tab.url,
      title: typeof tab.title === "string" ? tab.title : getManagedTabEntry(tabId)?.title ?? "",
    };
    await updateManagedTab(mergedTab);
  })();
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === BRIDGE_RECONNECT_ALARM) {
    connectBridge();
  }
});

chrome.runtime.onStartup.addListener(() => {
  void loadState();
  ensureReconnectAlarm();
  connectBridge();
});

chrome.runtime.onInstalled.addListener(() => {
  void loadState();
  ensureReconnectAlarm();
  connectBridge();
});

chrome.action.onClicked.addListener(() => {
  connectBridge();
});

void loadState().finally(() => {
  ensureReconnectAlarm();
  connectBridge();
});
