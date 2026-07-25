import path from "node:path";
import { isCommandName, renderCommandHelp, renderGeneralHelp } from "./help.js";
import type { CommandName } from "./types.js";

export interface ParsedInput {
  command?: CommandName;
  args: string[];
  options: Record<string, unknown>;
  localOutput?: { ok: boolean; text: string };
  allowAutoStart: boolean;
}

type OptionKind = "boolean" | "string" | "optional-string" | "non-negative-integer" | "positive-integer";

interface OptionRule {
  key: string;
  kind: OptionKind;
  maximum?: number;
}

interface CommandSchema {
  minArgs: number;
  maxArgs: number;
  options: Record<string, OptionRule>;
}

const booleanOption = (key: string): OptionRule => ({ key, kind: "boolean" });
const stringOption = (key: string): OptionRule => ({ key, kind: "string" });
const optionalStringOption = (key: string): OptionRule => ({ key, kind: "optional-string" });
const nonNegativeIntegerOption = (key: string, maximum?: number): OptionRule => ({ key, kind: "non-negative-integer", maximum });
const positiveIntegerOption = (key: string): OptionRule => ({ key, kind: "positive-integer" });

const TAB = stringOption("tab");
const NO_DELAY = booleanOption("noDelay");
const MAX_WAIT_MS = 2_147_000_000;

const COMMAND_SCHEMAS: Record<CommandName, CommandSchema> = {
  open: {
    minArgs: 1,
    maxArgs: 1,
    options: {
      "--new": booleanOption("new"),
      "--window": booleanOption("window"),
      "--tab": TAB,
      "--wait": stringOption("wait"),
      "--no-delay": NO_DELAY,
    },
  },
  tabs: { minArgs: 0, maxArgs: 0, options: {} },
  focus: { minArgs: 1, maxArgs: 1, options: {} },
  close: { minArgs: 1, maxArgs: 1, options: {} },
  "close-idle": {
    minArgs: 0,
    maxArgs: 0,
    options: {
      "--hours": positiveIntegerOption("hours"),
      "--dry-run": booleanOption("dryRun"),
    },
  },
  click: {
    minArgs: 1,
    maxArgs: 1,
    options: {
      "--tab": TAB,
      "--index": nonNegativeIntegerOption("index"),
      "--text": booleanOption("text"),
      "--coords": booleanOption("coords"),
      "--no-delay": NO_DELAY,
    },
  },
  type: {
    minArgs: 2,
    maxArgs: 2,
    options: {
      "--tab": TAB,
      "--index": nonNegativeIntegerOption("index"),
      "--no-delay": NO_DELAY,
    },
  },
  fill: {
    minArgs: 1,
    maxArgs: 2,
    options: {
      "--tab": TAB,
      "--clear": booleanOption("clear"),
      "--append": booleanOption("append"),
      "--index": nonNegativeIntegerOption("index"),
      "--no-delay": NO_DELAY,
    },
  },
  upload: {
    minArgs: 2,
    maxArgs: 2,
    options: {
      "--tab": TAB,
      "--no-delay": NO_DELAY,
    },
  },
  wait: {
    minArgs: 0,
    maxArgs: 1,
    options: {
      "--tab": TAB,
      "--text": stringOption("text"),
      "--gone": stringOption("gone"),
      "--stable": stringOption("stable"),
      "--ms": stringOption("ms"),
      "--timeout": nonNegativeIntegerOption("timeout", MAX_WAIT_MS),
    },
  },
  snapshot: {
    minArgs: 0,
    maxArgs: 0,
    options: {
      "--tab": TAB,
      "--scope": stringOption("scope"),
      "--depth": nonNegativeIntegerOption("depth"),
    },
  },
  diff: {
    minArgs: 0,
    maxArgs: 0,
    options: {
      "--tab": TAB,
      "--scope": stringOption("scope"),
      "--depth": nonNegativeIntegerOption("depth"),
    },
  },
  inspect: {
    minArgs: 0,
    maxArgs: 0,
    options: {
      "--tab": TAB,
      "--scope": stringOption("scope"),
      "--all": booleanOption("all"),
      "--coords": booleanOption("coords"),
    },
  },
  describe: {
    minArgs: 0,
    maxArgs: 0,
    options: {
      "--tab": TAB,
      "--scope": stringOption("scope"),
      "--model": stringOption("model"),
    },
  },
  ask: {
    minArgs: 1,
    maxArgs: 1,
    options: {
      "--tab": TAB,
      "--scope": stringOption("scope"),
      "--model": stringOption("model"),
    },
  },
  extract: {
    minArgs: 0,
    maxArgs: 1,
    options: {
      "--tab": TAB,
      "--scope": stringOption("scope"),
      "--json": booleanOption("json"),
      "--limit": positiveIntegerOption("limit"),
    },
  },
  screenshot: {
    minArgs: 0,
    maxArgs: 1,
    options: { "--tab": TAB },
  },
  html: {
    minArgs: 0,
    maxArgs: 1,
    options: {
      "--tab": TAB,
      "--limit": positiveIntegerOption("limit"),
    },
  },
  eval: {
    minArgs: 1,
    maxArgs: 1,
    options: { "--tab": TAB },
  },
  dialog: {
    minArgs: 0,
    maxArgs: 0,
    options: {
      "--tab": TAB,
      "--accept": optionalStringOption("accept"),
      "--dismiss": booleanOption("dismiss"),
    },
  },
  status: {
    minArgs: 0,
    maxArgs: 0,
    options: { "--tab": TAB },
  },
  stop: { minArgs: 0, maxArgs: 0, options: {} },
};

function commandFailure(command: CommandName, issue: string): ParsedInput {
  return {
    command,
    args: [],
    options: {},
    localOutput: { ok: false, text: renderCommandHelp(command, issue) },
    allowAutoStart: false,
  };
}

function parseInteger(flag: string, raw: string, positive: boolean): number | string {
  const pattern = positive ? /^[1-9]\d*$/ : /^(?:0|[1-9]\d*)$/;
  if (!pattern.test(raw)) {
    return `${flag} requires a ${positive ? "positive" : "non-negative"} whole number.`;
  }

  const parsed = Number(raw);
  if (!Number.isSafeInteger(parsed)) {
    return `${flag} must be a safe integer.`;
  }
  return parsed;
}

function validateDelay(value: string): string | null {
  const match = /^(0|[1-9]\d*)(?:-(0|[1-9]\d*))?$/.exec(value);
  if (!match) {
    return `Invalid --ms value "${value}". Use a non-negative integer or min-max range.`;
  }

  const minimum = Number(match[1]);
  const maximum = match[2] == null ? minimum : Number(match[2]);
  if (!Number.isSafeInteger(minimum) || !Number.isSafeInteger(maximum)) {
    return "--ms values must be safe integers.";
  }
  if (minimum > MAX_WAIT_MS || maximum > MAX_WAIT_MS) {
    return `--ms values must not exceed ${MAX_WAIT_MS}.`;
  }
  if (maximum < minimum) {
    return "--ms range maximum must be greater than or equal to its minimum.";
  }
  return null;
}

function argumentIssue(command: CommandName, args: string[], options: Record<string, unknown>): string | null {
  const schema = COMMAND_SCHEMAS[command];
  if (args.length < schema.minArgs) {
    switch (command) {
      case "open":
        return "Missing required argument <url>.";
      case "focus":
      case "close":
        return "Missing required argument <alias>.";
      case "click":
        return "Missing required argument <target>.";
      case "type":
        return "Missing required arguments <target> <text>.";
      case "fill":
        return "Missing required argument <target>.";
      case "upload":
        return "Missing required arguments <target> <filepath>.";
      case "ask":
        return "Missing required argument <question>.";
      case "eval":
        return "Missing required argument <js>.";
      default:
        return "Missing required argument.";
    }
  }

  if (args.length > schema.maxArgs) {
    return `Too many positional arguments (expected at most ${schema.maxArgs}). Quote arguments that contain spaces.`;
  }

  if (command === "close-idle" && options.hours == null) {
    return "Missing required option --hours <n>.";
  }

  if (command === "open" && options.window && options.tab) {
    return "--window creates an independent window and cannot be combined with --tab.";
  }

  if (command === "fill") {
    if (options.clear && options.append) {
      return "Use either --clear or --append, not both.";
    }
    if (options.clear && args.length > 1) {
      return "Do not provide <text> with --clear.";
    }
    if (!options.clear && args.length < 2) {
      return "Missing required argument <text> unless --clear is used.";
    }
  }

  if (command === "dialog" && options.accept && options.dismiss) {
    return "Use either --accept or --dismiss, not both.";
  }

  if (command === "wait") {
    const conditions = [args.length === 1, typeof options.text === "string", typeof options.gone === "string", typeof options.stable === "string", typeof options.ms === "string"].filter(Boolean).length;
    if (conditions !== 1) {
      return "Specify exactly one wait condition: [selector], --text, --gone, --stable, or --ms.";
    }
    if (typeof options.ms === "string") {
      return validateDelay(options.ms);
    }
  }

  return null;
}

function validateOptionValue(rule: OptionRule, value: unknown): boolean {
  switch (rule.kind) {
    case "boolean":
      return typeof value === "boolean";
    case "string":
      return typeof value === "string" && value.length > 0;
    case "optional-string":
      return value === true || (typeof value === "string" && value.length > 0);
    case "non-negative-integer":
      return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
    case "positive-integer":
      return typeof value === "number" && Number.isSafeInteger(value) && value > 0;
  }
}

/** Validate already-normalized input, including requests sent directly to the local server. */
export function validateCommandInput(command: CommandName, args: unknown, options: unknown): string | null {
  if (!Array.isArray(args) || !args.every((argument) => typeof argument === "string")) {
    return "Command arguments must be strings.";
  }
  if (typeof options !== "object" || options === null || Array.isArray(options)) {
    return "Command options must be an object.";
  }

  const normalizedOptions = options as Record<string, unknown>;
  const rulesByKey = new Map(Object.values(COMMAND_SCHEMAS[command].options).map((rule) => [rule.key, rule]));
  for (const [key, value] of Object.entries(normalizedOptions)) {
    const rule = rulesByKey.get(key);
    if (!rule) {
      return `Unsupported option "${key}" for browser ${command}.`;
    }
    if (!validateOptionValue(rule, value) || (rule.maximum != null && typeof value === "number" && value > rule.maximum)) {
      return `Invalid value for option "${key}".`;
    }
  }

  return argumentIssue(command, args, normalizedOptions);
}

export function parseCliInput(argv: string[], cwd = process.cwd()): ParsedInput {
  if (argv.length === 0 || (argv.length === 1 && ["help", "--help", "-h"].includes(argv[0]))) {
    return {
      args: [],
      options: {},
      localOutput: { ok: true, text: renderGeneralHelp() },
      allowAutoStart: false,
    };
  }

  if (["help", "--help", "-h"].includes(argv[0])) {
    return {
      args: [],
      options: {},
      localOutput: { ok: false, text: `[error] Help does not accept arguments.\n\n${renderGeneralHelp()}` },
      allowAutoStart: false,
    };
  }

  const [rawCommand, ...rest] = argv;
  if (!isCommandName(rawCommand)) {
    return {
      args: [],
      options: {},
      localOutput: { ok: false, text: `[error] Unknown command "${rawCommand}".\n\n${renderGeneralHelp()}` },
      allowAutoStart: false,
    };
  }

  if (rest.length === 1 && ["--help", "-h"].includes(rest[0])) {
    return {
      command: rawCommand,
      args: [],
      options: {},
      localOutput: { ok: true, text: renderCommandHelp(rawCommand) },
      allowAutoStart: false,
    };
  }
  if (rest.includes("--help") || rest.includes("-h")) {
    return commandFailure(rawCommand, "--help must be used by itself after the command.");
  }

  const schema = COMMAND_SCHEMAS[rawCommand];
  const args: string[] = [];
  const options: Record<string, unknown> = {};

  for (let index = 0; index < rest.length; index += 1) {
    const token = rest[index];
    if (!token.startsWith("--")) {
      args.push(token);
      continue;
    }

    const rule = schema.options[token];
    if (!rule) {
      return commandFailure(rawCommand, `Unsupported option "${token}".`);
    }
    if (Object.prototype.hasOwnProperty.call(options, rule.key)) {
      return commandFailure(rawCommand, `Option "${token}" may only be specified once.`);
    }

    if (rule.kind === "boolean") {
      options[rule.key] = true;
      continue;
    }

    if (rule.kind === "optional-string") {
      const candidate = rest[index + 1];
      if (candidate != null && !candidate.startsWith("--")) {
        options[rule.key] = candidate;
        index += 1;
      } else {
        options[rule.key] = true;
      }
      continue;
    }

    const value = rest[index + 1];
    if (value == null || value.startsWith("--")) {
      return commandFailure(rawCommand, `${token} requires a value.`);
    }
    index += 1;

    if (rule.kind === "string") {
      if (!value) {
        return commandFailure(rawCommand, `${token} requires a non-empty value.`);
      }
      options[rule.key] = value;
      continue;
    }

    const parsed = parseInteger(token, value, rule.kind === "positive-integer");
    if (typeof parsed === "string") {
      return commandFailure(rawCommand, parsed);
    }
    if (rule.maximum != null && parsed > rule.maximum) {
      return commandFailure(rawCommand, `${token} must not exceed ${rule.maximum}.`);
    }
    options[rule.key] = parsed;
  }

  if (options.window) {
    options.new = true;
  }

  const issue = argumentIssue(rawCommand, args, options);
  if (issue) {
    return commandFailure(rawCommand, issue);
  }

  if (rawCommand === "screenshot" && args[0]) {
    args[0] = path.resolve(cwd, args[0]);
  }
  if (rawCommand === "upload" && args[1]) {
    args[1] = path.resolve(cwd, args[1]);
  }

  return {
    command: rawCommand,
    args,
    options,
    allowAutoStart: rawCommand !== "stop",
  };
}
