import assert from "node:assert/strict";
import { test } from "node:test";
import {
  bindCommandTarget,
  commandQueueKey,
  KeyedSerialTaskQueue,
  SerialTaskQueue,
  SerializedStateStore,
} from "../extension/runtime-state.js";

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

test("state loading is shared and callers cannot observe half-loaded state", async () => {
  const gate = deferred();
  let getCalls = 0;
  let applied = null;
  const store = new SerializedStateStore({
    storage: {
      async get(keys) {
        getCalls += 1;
        assert.deepEqual(keys, ["managedTabs", "activeTabId"]);
        return gate.promise;
      },
      async set() {},
    },
    keys: ["managedTabs", "activeTabId"],
    read: () => applied,
    apply: (value) => {
      applied = value;
    },
    empty: () => ({ managedTabs: [], activeTabId: null }),
  });

  let firstFinished = false;
  let secondFinished = false;
  const first = store.load().then(() => {
    firstFinished = true;
  });
  const second = store.load().then(() => {
    secondFinished = true;
  });

  await Promise.resolve();
  assert.equal(getCalls, 1);
  assert.equal(firstFinished, false);
  assert.equal(secondFinished, false);

  const state = { managedTabs: [{ tabId: 1, alias: "t0" }], activeTabId: 1 };
  gate.resolve(state);
  await Promise.all([first, second]);
  assert.deepEqual(applied, state);
});

test("state writes use mutation-time snapshots and cannot overtake each other", async () => {
  const firstWrite = deferred();
  const writes = [];
  let state = { value: 0 };
  const store = new SerializedStateStore({
    storage: {
      async get() {
        return { value: 0 };
      },
      async set(snapshot) {
        writes.push(snapshot);
        if (writes.length === 1) {
          await firstWrite.promise;
        }
      },
    },
    keys: ["value"],
    read: () => state,
    apply: (value) => {
      state = value;
    },
    empty: () => ({ value: 0 }),
  });

  await store.load();
  state = { value: 1 };
  const first = store.save();
  state = { value: 2 };
  const second = store.save();

  await Promise.resolve();
  assert.deepEqual(writes, [{ value: 1 }]);
  firstWrite.resolve();
  await Promise.all([first, second]);
  assert.deepEqual(writes, [{ value: 1 }, { value: 2 }]);
});

test("failed storage operations preserve runtime state and do not block later writes", async () => {
  let calls = 0;
  let state = { value: 0 };
  const writes = [];
  const store = new SerializedStateStore({
    storage: {
      get: async () => ({ value: 0 }),
      async set(snapshot) {
        calls += 1;
        if (calls === 1) throw new Error("storage unavailable");
        writes.push(snapshot);
      },
    },
    keys: ["value"],
    read: () => state,
    apply: (value) => {
      state = value;
    },
    empty: () => ({ value: 0 }),
  });

  await store.load();
  state = { value: 1 };
  await store.save();
  state = { value: 2 };
  await store.save();
  assert.deepEqual(state, { value: 2 });
  assert.deepEqual(writes, [{ value: 2 }]);
});

test("request queue serializes tasks and recovers after a rejection", async () => {
  const queue = new SerialTaskQueue();
  const gate = deferred();
  const events = [];

  const first = queue.enqueue(async () => {
    events.push("first:start");
    await gate.promise;
    events.push("first:end");
    throw new Error("expected");
  });
  const second = queue.enqueue(async () => {
    events.push("second:start");
    events.push("second:end");
    return 42;
  });

  await Promise.resolve();
  assert.deepEqual(events, ["first:start"]);
  gate.resolve();
  await assert.rejects(first, /expected/);
  assert.equal(await second, 42);
  assert.deepEqual(events, ["first:start", "first:end", "second:start", "second:end"]);
});

test("implicit tab targets are pinned before queued execution", () => {
  const implicit = { selector: "main" };
  const pinned = bindCommandTarget("extract", implicit, 41);
  assert.deepEqual(pinned, { selector: "main", tabId: 41 });
  assert.notEqual(pinned, implicit);

  const explicit = { tabId: "t1" };
  assert.equal(bindCommandTarget("extract", explicit, 41), explicit);
  assert.equal(bindCommandTarget("status", implicit, 41), implicit);
  assert.equal(bindCommandTarget("tabs", implicit, 41), implicit);
  assert.equal(bindCommandTarget("close-idle", implicit, 41), implicit);
  assert.equal(bindCommandTarget("extract", implicit, null), implicit);
});

test("command lanes canonicalize aliases while isolating tabs and diagnostics", () => {
  const managed = [
    { tabId: 41, alias: "t0" },
    { tabId: 99, alias: "t1" },
  ];

  assert.equal(commandQueueKey("open", { tabId: "t0" }, managed, 99), "tab:41");
  assert.equal(commandQueueKey("extract", { alias: "t1" }, managed, 41), "tab:99");
  assert.equal(commandQueueKey("click", {}, managed, 41), "tab:41");
  assert.equal(commandQueueKey("status", {}, managed, 41), "diagnostic:status");
  assert.equal(commandQueueKey("close-idle", {}, managed, 41), "managed-tabs");
  assert.equal(commandQueueKey("open", { newTab: true }, managed, 41), "managed-tabs");
  assert.equal(commandQueueKey("open", { newTab: true, newWindow: true }, managed, 41), "managed-tabs");
});

test("a hung tab lane does not head-of-line block an isolated tab", async () => {
  const queue = new KeyedSerialTaskQueue();
  const hung = deferred();
  const events = [];

  const firstTabTask = queue.enqueue("tab:41", async () => {
    events.push("t0:start");
    await hung.promise;
    events.push("t0:end");
  });
  const blockedSameTabTask = queue.enqueue("tab:41", async () => {
    events.push("t0:next");
  });
  const isolatedTask = queue.enqueue("tab:99", async () => {
    events.push("t1:start");
    return "completed";
  });

  assert.equal(await isolatedTask, "completed");
  assert.deepEqual(events, ["t0:start", "t1:start"]);

  hung.resolve();
  await Promise.all([firstTabTask, blockedSameTabTask]);
  assert.deepEqual(events, ["t0:start", "t1:start", "t0:end", "t0:next"]);
});

test("expired work queued behind a hung request is skipped after reconnect", async () => {
  const queue = new KeyedSerialTaskQueue();
  const hung = deferred();
  const events = [];
  let oldSocketOpen = true;
  let now = 100;
  const deadline = 100;

  const hungOldRequest = queue.enqueue("tab:41", async () => {
    events.push("old:start");
    await hung.promise;
    events.push("old:settled");
  });
  const abandonedOldRequest = queue.enqueue(
    "tab:41",
    async () => {
      events.push("old:mutated");
    },
    { shouldStart: () => oldSocketOpen && now <= deadline },
  );

  now = 101;
  oldSocketOpen = false;
  const reconnectedOtherTab = queue.enqueue("tab:99", async () => {
    events.push("new:t1");
    return 99;
  });
  assert.equal(await reconnectedOtherTab, 99);
  assert.deepEqual(events, ["old:start", "new:t1"]);

  const reconnectedSameTab = queue.enqueue("tab:41", async () => {
    events.push("new:t0");
    return 41;
  });
  hung.resolve();

  await hungOldRequest;
  assert.equal(await abandonedOldRequest, undefined);
  assert.equal(await reconnectedSameTab, 41);
  assert.deepEqual(events, ["old:start", "new:t1", "old:settled", "new:t0"]);
});
