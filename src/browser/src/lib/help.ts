import type { CommandName } from "./types.js";

interface HelpSpec {
  name: CommandName;
  summary: string;
  usage: string;
  description: string;
  options: Array<{ flag: string; description: string }>;
  examples: string[];
  nextSteps: string[];
}

const HIDDEN_FROM_GENERAL_HELP = new Set<CommandName>(["html", "screenshot"]);

const COMMANDS: HelpSpec[] = [
  {
    name: "open",
    summary: "Navigate the managed Chrome tab and return a compact preview.",
    usage: "browser open <url> [--new] [--window] [--tab <alias>] [--wait <selector>] [--no-delay]",
    description:
      "Updates the active managed tab in your real Chrome session by default. The first command creates a dedicated automation window and tab, and all subsequent commands stay there unless you use --new or target a different tab with --tab.",
    options: [
      { flag: "--new", description: "Open the URL in a new managed tab and make it active." },
      { flag: "--window", description: "Used with --new: create a new Chrome window instead of a tab in the current window." },
      { flag: "--tab <alias>", description: "Navigate a specific managed tab alias such as t1." },
      { flag: "--wait <selector>", description: "Wait for a selector before returning." },
      { flag: "--no-delay", description: "Skip the built-in randomized post-action delay." },
    ],
    examples: ['browser open "https://news.ycombinator.com"', 'browser open "https://example.com/login" --wait "form"', 'browser open "https://github.com" --new', 'browser open "https://example.com" --new --window'],
    nextSteps: ["browser tabs", "browser snapshot", 'browser extract --scope "main"'],
  },
  {
    name: "tabs",
    summary: "List managed tabs and show which one is active.",
    usage: "browser tabs",
    description: "Shows every managed tab alias, its Chrome tab id, URL, title, and which tab receives commands by default.",
    options: [],
    examples: ["browser tabs"],
    nextSteps: ["browser focus t1", "browser close t1"],
  },
  {
    name: "focus",
    summary: "Switch the active managed tab.",
    usage: "browser focus <alias>",
    description: "Makes the selected managed tab active for subsequent commands and focuses that tab in Chrome.",
    options: [],
    examples: ["browser focus t1"],
    nextSteps: ['browser click "Continue"', "browser status"],
  },
  {
    name: "close",
    summary: "Close a managed tab and remove it from the registry.",
    usage: "browser close <alias>",
    description: "Closes the selected managed tab in Chrome. If it was active, another managed tab becomes active automatically.",
    options: [],
    examples: ["browser close t1"],
    nextSteps: ["browser tabs", 'browser open "https://example.com" --new'],
  },
  {
    name: "close-idle",
    summary: "Safely close idle tabs across all normal Chrome windows.",
    usage: "browser close-idle --hours <n> [--dry-run]",
    description:
      "Global cleanup for managed and unmanaged tabs in normal Chrome windows. Revalidates each candidate immediately before removal and always skips pinned, audible, active, non-normal-window, recently accessed, and timestamp-less tabs. Use --dry-run first.",
    options: [
      { flag: "--hours <n>", description: "Positive safe-integer hours of inactivity required for eligibility." },
      { flag: "--dry-run", description: "Revalidate and report eligible tabs without closing anything." },
    ],
    examples: ["browser close-idle --hours 6 --dry-run", "browser close-idle --hours 6"],
    nextSteps: ["browser tabs"],
  },
  {
    name: "click",
    summary: "Click an element by selector, visible text, or ref.",
    usage: "browser click <target> [--tab <alias>] [--index <n>] [--text] [--coords] [--no-delay]",
    description:
      "Clicks the first matching element by default. Targets like .submit use selectors; plain text targets match visible text. After inspect, ref IDs like e2 can be used directly.",
    options: [
      { flag: "--tab <alias>", description: "Run the command against a specific managed tab alias." },
      { flag: "--index <n>", description: "Choose the nth match when multiple elements match." },
      { flag: "--text", description: "Force a text-only search across visible elements." },
      { flag: "--coords", description: "Return the clicked element's bounding box." },
      { flag: "--no-delay", description: "Skip the built-in randomized post-action delay." },
    ],
    examples: ['browser click "More"', 'browser click "[data-e2e=post_button]"', 'browser click e2 --coords'],
    nextSteps: ["browser diff", "browser wait --text \"Success\""],
  },
  {
    name: "type",
    summary: "Clear an input and type new text into it for simple fields.",
    usage: "browser type <target> <text> [--tab <alias>] [--index <n>] [--no-delay]",
    description:
      "Finds an element, clears it, and fills it with DOM property updates. Prefer this for simple <input> and <textarea> elements. Use fill when framework state must update through trusted keyboard events.",
    options: [
      { flag: "--tab <alias>", description: "Run the command against a specific managed tab alias." },
      { flag: "--index <n>", description: "Choose the nth match when multiple elements match." },
      { flag: "--no-delay", description: "Skip the built-in randomized post-action delay." },
    ],
    examples: ['browser type \'input[name="q"]\' "browser CLI"', 'browser type "Search" "browser automation"'],
    nextSteps: ["browser click \"Search\"", "browser fill e3 \"replacement text\""],
  },
  {
    name: "fill",
    summary: "Type via real CDP keyboard events for React and rich-text editors.",
    usage: "browser fill <target> [text] [--tab <alias>] [--clear] [--append] [--index <n>] [--no-delay]",
    description:
      "Focus an element, optionally clear it, and type text via trusted CDP keyboard events. React, Draft.js, Vue, and contenteditable regions update their internal state correctly with this command.",
    options: [
      { flag: "--tab <alias>", description: "Run the command against a specific managed tab alias." },
      { flag: "--clear", description: "Only clear the field and stop." },
      { flag: "--append", description: "Skip the clear step and type at the current cursor position." },
      { flag: "--index <n>", description: "Choose the nth match when multiple elements match." },
      { flag: "--no-delay", description: "Skip the built-in randomized post-action delay." },
    ],
    examples: ['browser fill ".public-DraftEditor-content" "New caption"', 'browser fill e5 "Append this" --append', 'browser fill "Description" --clear'],
    nextSteps: ["browser diff", "browser inspect"],
  },
  {
    name: "upload",
    summary: "Attach a local file to a file input via Chrome DevTools Protocol.",
    usage: "browser upload <target> <filepath> [--tab <alias>] [--no-delay]",
    description:
      "Attach a local file to a file input element via Chrome DevTools Protocol. This is the reliable way to upload files because it avoids brittle OS dialog automation while still using Chrome's native file selection path.",
    options: [
      { flag: "--tab <alias>", description: "Run the command against a specific managed tab alias." },
      { flag: "--no-delay", description: "Skip the built-in randomized post-action delay." },
    ],
    examples: ['browser upload "input[type=file]" /path/to/video.mp4', "browser upload e4 /tmp/file.png"],
    nextSteps: ["browser wait --text \"Uploaded\"", "browser diff"],
  },
  {
    name: "wait",
    summary: "Wait for page state, text, disappearance, stability, or a fixed/random delay.",
    usage: "browser wait [selector] [--tab <alias>] [--text <text>] [--gone <selector>] [--stable <selector>] [--ms <n|min-max>] [--timeout <ms>]",
    description:
      "Wait for a condition on the page before continuing. Supports waiting for elements to appear, text to show up, elements to disappear, elements to stabilize, or a fixed/random time delay.",
    options: [
      { flag: "--tab <alias>", description: "Run the command against a specific managed tab alias." },
      { flag: "--text <text>", description: "Wait until the given text appears anywhere on the page." },
      { flag: "--gone <selector>", description: "Wait until the selector disappears or becomes invisible." },
      { flag: "--stable <selector>", description: "Wait until the selector stops mutating for 500ms." },
      { flag: "--ms <n|min-max>", description: "Wait a fixed or random number of milliseconds." },
      { flag: "--timeout <ms>", description: "Maximum wait time before failing. Default 15000." },
    ],
    examples: ['browser wait "main"', 'browser wait --text "Processing complete"', 'browser wait --ms 1000-3000'],
    nextSteps: ["browser snapshot", "browser diff"],
  },
  {
    name: "snapshot",
    summary: "Return a compact accessibility-tree view of the page.",
    usage: "browser snapshot [--tab <alias>] [--scope <selector>] [--depth <n>]",
    description:
      "Return Chrome's accessibility tree as a compact indented text representation. Use this as the primary page-understanding command when you need structure, labels, and interactive state.",
    options: [
      { flag: "--tab <alias>", description: "Run the command against a specific managed tab alias." },
      { flag: "--scope <selector>", description: "Limit the tree to a subtree rooted at the selector." },
      { flag: "--depth <n>", description: "Limit the output tree depth." },
    ],
    examples: ["browser snapshot", 'browser snapshot --scope "main" --depth 4'],
    nextSteps: ["browser diff", "browser inspect"],
  },
  {
    name: "diff",
    summary: "Show what changed since the last snapshot.",
    usage: "browser diff [--tab <alias>] [--scope <selector>] [--depth <n>]",
    description:
      "Takes a fresh accessibility snapshot and compares it with the prior snapshot in this session. If no baseline exists yet, returns a full snapshot and stores it for the next diff.",
    options: [
      { flag: "--tab <alias>", description: "Run the command against a specific managed tab alias." },
      { flag: "--scope <selector>", description: "Limit the underlying snapshot to a subtree rooted at the selector." },
      { flag: "--depth <n>", description: "Limit the underlying snapshot tree depth." },
    ],
    examples: ["browser diff", 'browser diff --scope "main"'],
    nextSteps: ["browser inspect", "browser ask \"what changed visually?\""],
  },
  {
    name: "inspect",
    summary: "Return JSON for interactive elements, including stable refs.",
    usage: "browser inspect [--tab <alias>] [--scope <selector>] [--all] [--coords]",
    description:
      "Return a JSON snapshot of interactive elements on the page: buttons, links, inputs, toggles, selects, and contenteditable regions. Each element gets a short ref ID like e1 for later targeting.",
    options: [
      { flag: "--tab <alias>", description: "Run the command against a specific managed tab alias." },
      { flag: "--scope <selector>", description: "Limit inspection to a subtree rooted at the selector." },
      { flag: "--all", description: "Include hidden elements such as file inputs." },
      { flag: "--coords", description: "Include bounding-box coordinates for each element." },
    ],
    examples: ["browser inspect", 'browser inspect --scope "main" --coords', "browser inspect --all"],
    nextSteps: ["browser click e2", "browser fill e3 \"new text\""],
  },
  {
    name: "describe",
    summary: "Use a small vision model to describe the current page.",
    usage: "browser describe [--tab <alias>] [--scope <selector>] [--model <name>]",
    description:
      "Take a screenshot and accessibility snapshot, send both to a fast vision model, and return a natural-language description. Use this when visual-only state matters more than structural page state.",
    options: [
      { flag: "--tab <alias>", description: "Run the command against a specific managed tab alias." },
      { flag: "--scope <selector>", description: "Scope the accessibility snapshot while keeping a full-page screenshot." },
      { flag: "--model <name>", description: "Override the default model (google/gemini-3.1-flash-lite-preview)." },
    ],
    examples: ["browser describe", 'browser describe --scope "main"'],
    nextSteps: ["browser ask \"what error message is visible?\"", "browser snapshot"],
  },
  {
    name: "ask",
    summary: "Ask a specific visual question about the current page.",
    usage: "browser ask <question> [--tab <alias>] [--scope <selector>] [--model <name>]",
    description:
      "Take a screenshot and accessibility snapshot, send both to a fast vision model with your question, and return a concise factual answer. Use this when a targeted visual check is cheaper than a screenshot review.",
    options: [
      { flag: "--tab <alias>", description: "Run the command against a specific managed tab alias." },
      { flag: "--scope <selector>", description: "Scope the accessibility snapshot while keeping a full-page screenshot." },
      { flag: "--model <name>", description: "Override the default model (google/gemini-3.1-flash-lite-preview)." },
    ],
    examples: ['browser ask "is the upload progress bar complete?"', 'browser ask "what text is in the error banner?" --scope "main"'],
    nextSteps: ["browser click", "browser wait"],
  },
  {
    name: "extract",
    summary: "Extract visible text or structured link/text items.",
    usage: "browser extract [selector] [--tab <alias>] [--scope <selector>] [--json] [--limit <n>]",
    description:
      "Without a selector, extracts visible page text. With --json, returns compact {text, href} objects from matching elements. Use --scope to avoid mixing navigation, footer, and sidebar content into one output.",
    options: [
      { flag: "--tab <alias>", description: "Run the command against a specific managed tab alias." },
      { flag: "--scope <selector>", description: "Use a root element before extracting text or matching the selector." },
      { flag: "--json", description: "Return JSON instead of plain text." },
      { flag: "--limit <n>", description: "Maximum number of items to return." },
    ],
    examples: ['browser extract --scope "main" --limit 40', 'browser extract ".titleline" --json --limit 5'],
    nextSteps: ["browser snapshot", 'browser html "main" --limit 80'],
  },
  {
    name: "screenshot",
    summary: "Save a PNG screenshot of the managed Chrome tab.",
    usage: "browser screenshot [path] [--tab <alias>]",
    description:
      "Attempts full-page capture through Chrome DevTools Protocol. If unavailable, it falls back to visible-viewport capture.",
    options: [{ flag: "--tab <alias>", description: "Run the command against a specific managed tab alias." }],
    examples: ["browser screenshot", "browser screenshot ./artifacts/page.png"],
    nextSteps: ["browser describe", "browser status"],
  },
  {
    name: "html",
    summary: "Return cleaned HTML for the full page or a selector.",
    usage: "browser html [selector] [--tab <alias>] [--limit <n>]",
    description: "Returns normalized markup without scripts/styles, truncated by line count for readability.",
    options: [
      { flag: "--tab <alias>", description: "Run the command against a specific managed tab alias." },
      { flag: "--limit <n>", description: "Maximum number of lines to show." },
    ],
    examples: ["browser html", 'browser html "main" --limit 80'],
    nextSteps: ["browser snapshot", "browser extract"],
  },
  {
    name: "eval",
    summary: "Evaluate JavaScript in the active page context.",
    usage: "browser eval <js> [--tab <alias>]",
    description: "Runs JavaScript in the active tab and prints the result as JSON or text.",
    options: [{ flag: "--tab <alias>", description: "Run the command against a specific managed tab alias." }],
    examples: ['browser eval "document.title"', 'browser eval "Array.from(document.links).length"'],
    nextSteps: ["browser status", "browser inspect"],
  },
  {
    name: "dialog",
    summary: "Check for or handle browser-level dialogs that block automation.",
    usage: "browser dialog [--tab <alias>] [--accept [text]] [--dismiss]",
    description:
      "Check for and handle browser-level dialogs such as alert, confirm, prompt, and beforeunload dialogs. These dialogs block other browser commands while open.",
    options: [
      { flag: "--tab <alias>", description: "Run the command against a specific managed tab alias." },
      { flag: "--accept [text]", description: "Accept the dialog, optionally supplying prompt text." },
      { flag: "--dismiss", description: "Dismiss the dialog." },
    ],
    examples: ["browser dialog", "browser dialog --accept", 'browser dialog --accept "yes"'],
    nextSteps: ["browser click", "browser wait"],
  },
  {
    name: "status",
    summary: "Show managed automation tab URL, title, and bridge health.",
    usage: "browser status [--tab <alias>]",
    description: "Reports CLI server uptime plus extension connection and managed tab state. With --tab, shows status for a specific managed tab.",
    options: [{ flag: "--tab <alias>", description: "Show status for a specific managed tab alias." }],
    examples: ["browser status"],
    nextSteps: ["browser open https://example.com", "browser stop"],
  },
  {
    name: "stop",
    summary: "Stop the local browser server.",
    usage: "browser stop",
    description: "Shuts down the background CLI server and websocket bridge.",
    options: [],
    examples: ["browser stop"],
    nextSteps: ["browser open https://example.com"],
  },
];

export function isCommandName(value: string): value is CommandName {
  return COMMANDS.some((command) => command.name === value);
}

export function getHelpSpec(name: CommandName): HelpSpec {
  const spec = COMMANDS.find((command) => command.name === name);
  if (!spec) {
    throw new Error(`Unknown command: ${name}`);
  }
  return spec;
}

export function renderGeneralHelp(): string {
  const visibleCommands = COMMANDS.filter((command) => !HIDDEN_FROM_GENERAL_HELP.has(command.name));
  const lines = [
    "browser",
    "",
    "Control your real Chrome in a dedicated automation window through a local extension bridge.",
    "",
    "Commands:",
    ...visibleCommands.map((command) => `  ${command.name.padEnd(10)} ${command.summary}`),
    "",
    "Common option (only on commands that list it):",
    "  --tab <alias>   Target a specific managed tab.",
    "",
    "Example workflow:",
    '  browser open "https://news.ycombinator.com"',
    "  browser snapshot",
    "  browser inspect",
    '  browser click "More"',
    "  browser stop",
    "",
    "Navigation:",
    "  browser help",
    "  browser <command> --help",
    "  browser click           # usage + examples + next steps",
  ];
  return lines.join("\n");
}

export function renderCommandHelp(name: CommandName, issue?: string): string {
  const spec = getHelpSpec(name);
  const lines: string[] = [];

  if (issue) {
    lines.push(`[error] ${issue}`, "");
  }

  lines.push(spec.usage, "", spec.description);

  if (spec.options.length > 0) {
    lines.push("", "Options:");
    for (const option of spec.options) {
      lines.push(`  ${option.flag.padEnd(16)} ${option.description}`);
    }
  }

  lines.push("", "Examples:");
  for (const example of spec.examples) {
    lines.push(`  ${example}`);
  }

  lines.push("", "Next steps:");
  for (const nextStep of spec.nextSteps) {
    lines.push(`  ${nextStep}`);
  }

  return lines.join("\n");
}
