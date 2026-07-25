import assert from "node:assert/strict";
import { test } from "node:test";
import {
  assertManagedTabRegistered,
  captureTargetViaCdp,
  resolveManagedTabIdentifier,
} from "../extension/browser-boundaries.js";

const managed = [
  { tabId: 41, alias: "t0" },
  { tabId: 99, alias: "123" },
];

test("tab resolution never treats numeric strings as raw Chrome tab ids", () => {
  assert.equal(resolveManagedTabIdentifier(managed, 41, { tabId: "t0" }), 41);
  assert.equal(resolveManagedTabIdentifier(managed, 41, { tabId: "123" }), 99, "an exact registered alias remains valid");
  assert.throws(() => resolveManagedTabIdentifier(managed, 41, { tabId: "41" }), /Unknown managed tab alias/);
  assert.throws(() => resolveManagedTabIdentifier(managed, 41, { alias: "99" }), /Unknown managed tab alias/);
});

test("raw integer ids must already be registered", () => {
  assert.equal(resolveManagedTabIdentifier(managed, 41, { tabId: 41 }), 41);
  assert.equal(assertManagedTabRegistered(managed, 99), 99);
  assert.throws(() => resolveManagedTabIdentifier(managed, 41, { tabId: 777 }), /Unknown managed tab id/);
  assert.throws(() => assertManagedTabRegistered(managed, 777), /not a registered managed tab/);
});

test("compressed screenshots use only target-specific CDP viewport capture", async () => {
  const calls = [];
  const result = await captureTargetViaCdp({
    tabId: 41,
    fullPage: false,
    format: "jpeg",
    quality: 70,
    captureFullPage: async () => {
      throw new Error("full-page must not run");
    },
    captureViewport: async (...args) => {
      calls.push(args);
      return "data:image/jpeg;base64,target";
    },
  });

  assert.deepEqual(calls, [[41, "jpeg", 70]]);
  assert.deepEqual(result, { dataUrl: "data:image/jpeg;base64,target", mode: "viewport" });
});

test("full-page CDP failure falls back to the same target's CDP viewport", async () => {
  const calls = [];
  const result = await captureTargetViaCdp({
    tabId: 99,
    fullPage: true,
    captureFullPage: async (tabId) => {
      calls.push(["full", tabId]);
      throw new Error("layout too large");
    },
    captureViewport: async (tabId, format) => {
      calls.push(["viewport", tabId, format]);
      return "data:image/png;base64,target";
    },
  });

  assert.deepEqual(calls, [["full", 99], ["viewport", 99, "png"]]);
  assert.equal(result.dataUrl, "data:image/png;base64,target");
  assert.equal(result.mode, "viewport");
  assert.match(result.warning, /layout too large/);
});

test("CDP screenshot failure reports both full-page and viewport errors", async () => {
  await assert.rejects(
    captureTargetViaCdp({
      tabId: 41,
      fullPage: true,
      captureFullPage: async () => {
        throw new Error("full failure");
      },
      captureViewport: async () => {
        throw new Error("viewport failure");
      },
    }),
    (error) => {
      assert.match(error.message, /full-page CDP capture failed \(full failure\)/);
      assert.match(error.message, /target-specific CDP viewport capture failed \(viewport failure\)/);
      return true;
    },
  );
});
