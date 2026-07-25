import assert from "node:assert/strict";
import { test } from "node:test";
import { SerialTaskQueue, SerializedStateStore } from "../extension/runtime-state.js";

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
