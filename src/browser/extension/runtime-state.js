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

/** A tiny serial queue used to keep extension commands from racing each other. */
export class SerialTaskQueue {
  constructor() {
    this.tail = Promise.resolve();
  }

  enqueue(task) {
    const result = this.tail.then(task, task);
    this.tail = result.catch(() => undefined);
    return result;
  }
}
