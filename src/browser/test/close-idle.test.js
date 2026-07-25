import assert from "node:assert/strict";
import { describe, test } from "node:test";
import { assertValidIdleHours, closeIdleTabs } from "../extension/close-idle.js";

const HOUR = 60 * 60 * 1000;
const NOW = 2_000_000_000_000;

function oldTab(id, overrides = {}) {
  return {
    id,
    windowId: 1,
    url: `https://example.com/${id}`,
    title: `Tab ${id}`,
    active: false,
    pinned: false,
    audible: false,
    lastAccessed: NOW - 10 * HOUR,
    ...overrides,
  };
}

describe("close-idle safety", () => {
  test("requires positive safe-integer hours at the extension boundary", () => {
    for (const value of [1, 6, Number.MAX_SAFE_INTEGER]) {
      assert.doesNotThrow(() => assertValidIdleHours(value));
    }
    for (const value of [0, -1, 1.5, Number.MAX_SAFE_INTEGER + 1, NaN, Infinity, "6", null]) {
      assert.throws(() => assertValidIdleHours(value), /positive safe integer/);
    }
  });

  test("selects globally but skips protected tabs and revalidates every candidate", async () => {
    const normalTabs = [
      oldTab(1, { active: true }),
      oldTab(2, { pinned: true }),
      oldTab(3, { audible: true }),
      oldTab(4, { lastAccessed: undefined }),
      oldTab(5, { lastAccessed: NOW - HOUR }),
      oldTab(6),
      oldTab(7),
      oldTab(8),
      oldTab(9),
      oldTab(10),
      oldTab(11),
    ];
    const popupTab = oldTab(13, { windowId: 3 });
    const byId = new Map(normalTabs.map((tab) => [tab.id, tab]));
    const removed = [];
    const revalidated = [];

    const chromeApi = {
      windows: {
        async getAll(options) {
          assert.deepEqual(options, { populate: true });
          return [
            { id: 1, type: "normal", tabs: normalTabs },
            { id: 3, type: "popup", tabs: [popupTab] },
          ];
        },
        async get(windowId, options) {
          assert.deepEqual(options, { populate: false });
          return { id: windowId, type: windowId === 2 ? "popup" : "normal" };
        },
      },
      tabs: {
        async get(id) {
          revalidated.push(id);
          if (id === 8) throw new Error(`No tab with id: ${id}`);
          if (id === 10) throw new Error("tabs permission temporarily unavailable");
          const tab = { ...byId.get(id) };
          if (id === 7) tab.active = true;
          if (id === 11) tab.windowId = 2;
          return tab;
        },
        async remove(id) {
          if (id === 9) throw new Error("Chrome refused removal");
          removed.push(id);
        },
      },
    };

    const result = await closeIdleTabs({ chromeApi, hours: 6, now: () => NOW });

    assert.deepEqual(revalidated, [6, 6, 7, 7, 8, 9, 9, 10, 11, 11]);
    assert.deepEqual(removed, [6]);
    assert.deepEqual(result.closed.map((tab) => tab.id), [6]);
    assert.deepEqual(result.eligible.map((tab) => tab.id), [6, 9]);
    assert.equal(result.eligibleCount, 2);
    assert.equal(result.closedCount, 1);
    assert.equal(result.skippedCount, 9);
    assert.equal(result.failedCount, 2);
    assert.deepEqual(
      new Map(result.skipped.map((tab) => [tab.id, tab.reason])),
      new Map([
        [1, "active"],
        [2, "pinned"],
        [3, "audible"],
        [4, "missing-last-accessed"],
        [5, "not-idle"],
        [7, "revalidated-active"],
        [8, "vanished"],
        [11, "revalidated-non-normal-window"],
        [13, "non-normal-window"],
      ]),
    );
    assert.deepEqual(result.failed.map(({ id, stage }) => [id, stage]), [[9, "close"], [10, "revalidate"]]);
  });

  test("uses a final tab fetch after windows.get to catch protection changes and moves", async () => {
    const tabs = [oldTab(40), oldTab(41), oldTab(42), oldTab(43)];
    const byId = new Map(tabs.map((tab) => [tab.id, { ...tab }]));
    const finalStates = new Map([
      [40, { active: true }],
      [41, { pinned: true }],
      [42, { audible: true }],
      [43, { windowId: 2 }],
    ]);
    const fetchCounts = new Map();
    const removed = [];
    const chromeApi = {
      windows: {
        getAll: async () => [{ id: 1, type: "normal", tabs }],
        get: async (windowId) => {
          assert.equal(windowId, 1);
          // Model the state changing while the asynchronous window lookup is
          // pending. Only the subsequent tabs.get can observe this state.
          await Promise.resolve();
          return { id: 1, type: "normal" };
        },
      },
      tabs: {
        get: async (id) => {
          const count = (fetchCounts.get(id) || 0) + 1;
          fetchCounts.set(id, count);
          return count === 1 ? { ...byId.get(id) } : { ...byId.get(id), ...finalStates.get(id) };
        },
        remove: async (id) => removed.push(id),
      },
    };

    const result = await closeIdleTabs({ chromeApi, hours: 6, now: () => NOW });

    assert.deepEqual(removed, []);
    assert.deepEqual(Array.from(fetchCounts.entries()), [[40, 2], [41, 2], [42, 2], [43, 2]]);
    assert.deepEqual(
      new Map(result.skipped.map(({ id, reason }) => [id, reason])),
      new Map([
        [40, "revalidated-active"],
        [41, "revalidated-pinned"],
        [42, "revalidated-audible"],
        [43, "revalidated-window-changed"],
      ]),
    );
    assert.equal(result.eligibleCount, 0);
    assert.equal(result.failedCount, 0);
  });

  test("dry-run revalidates and reports without removing anything", async () => {
    const tab = oldTab(20);
    let removeCalls = 0;
    const chromeApi = {
      windows: {
        getAll: async () => [{ id: 1, type: "normal", tabs: [tab] }],
        get: async () => ({ id: 1, type: "normal" }),
      },
      tabs: {
        get: async () => ({ ...tab }),
        remove: async () => {
          removeCalls += 1;
        },
      },
    };

    const result = await closeIdleTabs({ chromeApi, hours: 6, dryRun: true, now: () => NOW });
    assert.equal(removeCalls, 0);
    assert.equal(result.dryRun, true);
    assert.equal(result.eligibleCount, 1);
    assert.equal(result.closedCount, 0);
    assert.deepEqual(result.eligible.map(({ id }) => id), [20]);
  });

  test("cancellation is checked again immediately before destructive removal", async () => {
    const tab = oldTab(25);
    let checks = 0;
    let removeCalls = 0;
    const chromeApi = {
      windows: {
        getAll: async () => [{ id: 1, type: "normal", tabs: [tab] }],
        get: async () => ({ id: 1, type: "normal" }),
      },
      tabs: {
        get: async () => ({ ...tab }),
        remove: async () => {
          removeCalls += 1;
        },
      },
    };

    const result = await closeIdleTabs({
      chromeApi,
      hours: 1,
      now: () => NOW,
      shouldContinue: () => {
        checks += 1;
        return checks < 3;
      },
    });
    assert.equal(result.eligibleCount, 1);
    assert.equal(removeCalls, 0);
  });

  test("a tab that vanishes during removal does not abort later candidates", async () => {
    const tabs = [oldTab(30), oldTab(31)];
    const removed = [];
    const chromeApi = {
      windows: {
        getAll: async () => [{ id: 1, type: "normal", tabs }],
        get: async () => ({ id: 1, type: "normal" }),
      },
      tabs: {
        get: async (id) => ({ ...tabs.find((tab) => tab.id === id) }),
        remove: async (id) => {
          if (id === 30) throw new Error("No tab with id: 30");
          removed.push(id);
        },
      },
    };

    const result = await closeIdleTabs({ chromeApi, hours: 1, now: () => NOW });
    assert.deepEqual(removed, [31]);
    assert.deepEqual(result.closed.map(({ id }) => id), [31]);
    assert.equal(result.skipped.find(({ id }) => id === 30)?.reason, "vanished-before-close");
    assert.equal(result.failedCount, 0);
  });
});
