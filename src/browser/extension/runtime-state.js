/** Serialize MV3 session-state loading and writes across concurrent callers. */
export class SerializedStateStore {
  constructor({ storage, keys, read, apply, empty }) {
    this.storage = storage;
    this.keys = keys;
    this.read = read;
    this.apply = apply;
    this.empty = empty;
    this.loaded = false;
    this.loadPromise = null;
    this.writeTail = Promise.resolve();
  }

  async load() {
    if (this.loaded) {
      return;
    }
    if (this.loadPromise) {
      return this.loadPromise;
    }

    this.loadPromise = (async () => {
      try {
        this.apply(await this.storage.get(this.keys));
      } catch {
        this.apply(this.empty());
      } finally {
        this.loaded = true;
        this.loadPromise = null;
      }
    })();

    return this.loadPromise;
  }

  async save() {
    if (!this.loaded) {
      await this.load();
    }
    // Capture a complete immutable snapshot at mutation time, then preserve
    // write order even if chrome.storage resolves writes out of order.
    const snapshot = structuredClone(this.read());
    const write = this.writeTail.then(() => this.storage.set(snapshot));
    this.writeTail = write.catch(() => undefined);
    await write.catch(() => undefined);
  }
}

/** A tiny serial queue used to keep operations on one resource from racing. */
export class SerialTaskQueue {
  constructor() {
    this.tail = Promise.resolve();
  }

  enqueue(task, options = {}) {
    const run = () => (options.shouldStart && !options.shouldStart() ? undefined : task());
    const result = this.tail.then(run, run);
    this.tail = result.catch(() => undefined);
    return result;
  }
}

/**
 * Serialize commands per resource without coupling unrelated browser tabs.
 *
 * A lane deliberately remains blocked while its active task is unsettled. Most
 * Chrome extension APIs cannot be aborted safely; advancing that lane after a
 * timeout would let abandoned work resume and race a newer command. Other
 * lanes remain independent, and expired/cancelled queued tasks are skipped.
 */
export class KeyedSerialTaskQueue {
  constructor() {
    this.lanes = new Map();
  }

  enqueue(key, task, options = {}) {
    const laneKey = String(key);
    let lane = this.lanes.get(laneKey);
    if (!lane) {
      lane = new SerialTaskQueue();
      this.lanes.set(laneKey, lane);
    }

    const result = lane.enqueue(task, options);
    const tail = lane.tail;
    void tail.finally(() => {
      if (this.lanes.get(laneKey) === lane && lane.tail === tail) {
        this.lanes.delete(laneKey);
      }
    });
    return result;
  }
}

/** Accept a timed-out navigation when its parsed document is already usable. */
export function isUsableTimedOutDocument(readyState, hasBodyText) {
  return (readyState === "interactive" || readyState === "complete") && hasBodyText === true;
}

/** Pin an implicit tab command before it waits in a queue. */
export function bindCommandTarget(action, params = {}, activeTabId = null) {
  if (!Number.isInteger(activeTabId) || action === "status" || action === "tabs" || action === "close-idle") {
    return params;
  }

  const hasExplicitTarget =
    params.tabId != null && !(typeof params.tabId === "string" && !params.tabId.trim()) ||
    params.alias != null && !(typeof params.alias === "string" && !params.alias.trim());
  return hasExplicitTarget ? params : { ...params, tabId: activeTabId };
}

/** Return the narrowest safe command lane known before command execution. */
export function commandQueueKey(action, params = {}, managedEntries = [], activeTabId = null) {
  // Status is a side-effect-free diagnostic from the scheduler's perspective;
  // it must remain usable to distinguish a stuck tab lane from disconnection.
  if (action === "status") {
    return "diagnostic:status";
  }

  // These inspect or mutate the managed-tab registry rather than one page.
  // New-tab creation must not inherit a poisoned active-tab lane: it is the
  // recovery path for callers when one page is stuck.
  if (action === "tabs" || action === "close-idle" || (action === "open" && params.newTab)) {
    return "managed-tabs";
  }

  const rawIdentifier = params.tabId ?? params.alias;
  if (Number.isInteger(rawIdentifier)) {
    return `tab:${rawIdentifier}`;
  }
  if (typeof rawIdentifier === "string" && rawIdentifier.trim()) {
    const identifier = rawIdentifier.trim();
    const matchingEntry = Array.from(managedEntries || []).find((entry) => entry?.alias === identifier);
    return matchingEntry && Number.isInteger(matchingEntry.tabId)
      ? `tab:${matchingEntry.tabId}`
      : `tab-alias:${identifier}`;
  }

  // Implicit commands address the currently managed tab. Canonicalizing it to
  // the Chrome id preserves serialization with commands using its alias.
  if (Number.isInteger(activeTabId)) {
    return `tab:${activeTabId}`;
  }
  return "implicit-tab";
}
