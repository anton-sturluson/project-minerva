import assert from "node:assert/strict";
import { describe, test } from "node:test";
import { parseCliInput, validateCommandInput } from "../src/lib/parse.js";
import type { CommandName } from "../src/lib/types.js";

function parseOk(argv: string[]) {
  const parsed = parseCliInput(argv, "/tmp/browser-parse-test");
  assert.equal(parsed.localOutput, undefined, parsed.localOutput?.text);
  assert.ok(parsed.command);
  return parsed;
}

function parseError(argv: string[], pattern: RegExp) {
  const parsed = parseCliInput(argv);
  assert.equal(parsed.localOutput?.ok, false);
  assert.match(parsed.localOutput?.text ?? "", pattern);
}

describe("command-specific CLI parsing", () => {
  const validCommands: Array<[CommandName, string[]]> = [
    ["open", ["https://example.com", "--new", "--window", "--wait", "main", "--no-delay"]],
    ["tabs", []],
    ["focus", ["t0"]],
    ["close", ["t0"]],
    ["close-idle", ["--hours", "6", "--dry-run"]],
    ["click", ["button", "--tab", "t0", "--index", "0", "--text", "--coords", "--no-delay"]],
    ["type", ["input", "hello", "--tab", "t0", "--index", "1", "--no-delay"]],
    ["fill", ["input", "hello", "--tab", "t0", "--append", "--index", "1", "--no-delay"]],
    ["upload", ["input", "./file.txt", "--tab", "t0", "--no-delay"]],
    ["wait", ["--text", "ready", "--tab", "t0", "--timeout", "1000"]],
    ["snapshot", ["--tab", "t0", "--scope", "main", "--depth", "3"]],
    ["diff", ["--tab", "t0", "--scope", "main", "--depth", "3"]],
    ["inspect", ["--tab", "t0", "--scope", "main", "--all", "--coords"]],
    ["describe", ["--tab", "t0", "--scope", "main", "--model", "model/name"]],
    ["ask", ["what is visible?", "--tab", "t0", "--scope", "main", "--model", "model/name"]],
    ["extract", ["a", "--tab", "t0", "--scope", "main", "--json", "--limit", "5"]],
    ["screenshot", ["./shot.png", "--tab", "t0"]],
    ["html", ["main", "--tab", "t0", "--limit", "80"]],
    ["eval", ["document.title", "--tab", "t0"]],
    ["dialog", ["--tab", "t0", "--accept", "yes"]],
    ["status", ["--tab", "t0"]],
    ["stop", []],
  ];

  for (const [command, argv] of validCommands) {
    test(`accepts the documented ${command} form`, () => {
      const parsed = parseOk([command, ...argv]);
      assert.equal(parsed.command, command);
    });
  }

  test("normalizes paths and --window semantics", () => {
    const upload = parseOk(["upload", "input", "relative.txt"]);
    assert.equal(upload.args[1], "/tmp/browser-parse-test/relative.txt");

    const screenshot = parseOk(["screenshot", "shot.png"]);
    assert.equal(screenshot.args[0], "/tmp/browser-parse-test/shot.png");

    const open = parseOk(["open", "example.com", "--window"]);
    assert.deepEqual(open.options, { window: true, new: true });
    assert.deepEqual(parseOk(["open", "example.com", "--tab", "t0"]).options, { tab: "t0" });
  });

  test("supports all wait modes and fill --clear", () => {
    for (const argv of [["wait", "main"], ["wait", "--gone", ".spinner"], ["wait", "--stable", "main"], ["wait", "--ms", "10-20"]]) {
      parseOk(argv);
    }
    parseOk(["fill", "input", "--clear"]);
    parseOk(["dialog", "--accept"]);
    parseOk(["dialog", "--dismiss"]);
  });

  test("rejects unsupported options per command, including --tab on global cleanup", () => {
    parseError(["close-idle", "--hours", "6", "--tab", "t0"], /Unsupported option "--tab"/);
    parseError(["tabs", "--json"], /Unsupported option "--json"/);
    parseError(["click", "button", "--dry-run"], /Unsupported option "--dry-run"/);
    parseError(["status", "--all"], /Unsupported option "--all"/);
  });

  test("rejects surplus positional arguments rather than ignoring them", () => {
    parseError(["tabs", "extra"], /Too many positional arguments/);
    parseError(["focus", "t0", "extra"], /Too many positional arguments/);
    parseError(["click", "one", "two"], /Too many positional arguments/);
    parseError(["ask", "unquoted", "question"], /Too many positional arguments/);
    parseError(["status", "extra"], /Too many positional arguments/);
  });

  test("rejects duplicate and ambiguous options", () => {
    parseError(["click", "button", "--index", "1", "--index", "2"], /only be specified once/);
    parseError(["dialog", "--accept", "--dismiss"], /either --accept or --dismiss/);
    parseError(["fill", "input", "text", "--clear"], /Do not provide <text>/);
    parseError(["fill", "input", "text", "--clear", "--append"], /either --clear or --append/);
    parseError(["wait", "main", "--text", "ready"], /exactly one wait condition/);
    parseError(["wait"], /exactly one wait condition/);
    parseError(["open", "example.com", "--window", "--tab", "t0"], /cannot be combined/);
  });

  test("does not let --help hide invalid trailing input", () => {
    parseError(["click", "button", "--help"], /--help must be used by itself/);
    parseError(["help", "click"], /Help does not accept arguments/);
    assert.equal(parseCliInput(["click", "--help"]).localOutput?.ok, true);
  });
});

describe("strict numeric parsing", () => {
  test("accepts positive safe-integer hours", () => {
    assert.equal(parseOk(["close-idle", "--hours", "1"]).options.hours, 1);
    assert.equal(parseOk(["close-idle", "--hours", String(Number.MAX_SAFE_INTEGER)]).options.hours, Number.MAX_SAFE_INTEGER);
  });

  test("rejects malformed, non-positive, fractional, and unsafe hours", () => {
    for (const value of ["", "0", "-1", "1.5", "6hours", "+6", " 6", "9007199254740992", "Infinity", "1e3"]) {
      parseError(["close-idle", "--hours", value], /(?:requires a value|positive whole number|safe integer)/);
    }
  });

  test("applies strict integer parsing to other integer options", () => {
    parseError(["click", "button", "--index", "2x"], /non-negative whole number/);
    parseError(["extract", "--limit", "1.5"], /positive whole number/);
    parseError(["wait", "--ms", "1", "--timeout", "10ms"], /non-negative whole number/);
    parseError(["snapshot", "--depth", "-1"], /non-negative whole number/);
    parseError(["wait", "--ms", "20-10"], /maximum must be greater/);
    parseError(["wait", "--ms", "1x"], /Invalid --ms/);
    parseError(["wait", "--ms", "2147000001"], /must not exceed/);
    parseError(["wait", "--text", "ready", "--timeout", "2147000001"], /must not exceed/);
  });
});

test("direct command requests receive the same option and argument validation", () => {
  assert.match(validateCommandInput("close-idle", [], { hours: 1, tab: "t0" }) ?? "", /Unsupported option/);
  assert.match(validateCommandInput("close-idle", [], { hours: 1.5 }) ?? "", /Invalid value/);
  assert.match(validateCommandInput("tabs", ["extra"], {}) ?? "", /Too many positional/);
  assert.equal(validateCommandInput("close-idle", [], { hours: 1, dryRun: true }), null);
});
