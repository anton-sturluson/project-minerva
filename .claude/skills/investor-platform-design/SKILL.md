---
name: investor-platform-design
description: Design, implement, or review Minerva investor-platform interfaces using the approved Homepage Club visual direction. Use for this project's frontend, components, and design mockups; not for other Minerva dashboards, reports, or backend-only work.
---

# Investor Platform Design

Homepage Club is the user-selected direction. Preserve its plain, slightly eccentric early-web character as the platform grows.

## Start from the approved reference

- Read [the design guide](../../../investor-platform/design/README.md) for the decision, palette, type, and interaction rules.
- Open [the standalone Homepage Club reference](../../../investor-platform/design/homepage-club.html) in a browser before substantial visual work. It contains portfolio, notebook, and source-index views.
- Inspect [the editable fragment](../../../investor-platform/design/homepage-club.fragment.html) for exact CSS values and proportions. Use the `.mv3.home` treatment; inactive styles from other explorations in this snapshot are not approved directions.

Resolve these paths from this skill's directory within the current checkout, including when invoked through `.agents/skills/`. Do not depend on files in a previous chat's visualization directory.

## Apply the design to real features

Keep the expressive masthead, blue underlined links, bracket navigation, warm paper, plum and pale-yellow details, and small web badges. Keep tables precise and quiet. Adapt these motifs to the feature rather than repeating every decoration on every screen.

Use the app's current components and stack; the reference is a visual specification, not production application code. Its sample portfolio, research prompts, preview state, and decorative badges are not real data or evidence that a feature has been built. Do not port the standalone preview runtime into the app.

Extend only the requested feature. Preserve real loading, empty, error, and recovery states. Use available financial data honestly; an unavailable return or alpha stays unavailable rather than becoming an invented number.

Maintain readable type, native keyboard focus, semantic controls, and responsive reflow. Nostalgia does not require inaccessible text, blinking graphics, fixed desktop widths, or simulated browser chrome.

## Check in the browser

For UI changes, exercise the actual changed workflow and its relevant failure or empty state. Inspect desktop and narrow layouts, including any wide financial table. Compare the result with Homepage Club and check that its character has survived. Follow the application's own verification instructions for code changes; do not claim unrun checks.

Record intentional design changes in the guide when the user requests a new direction. Keep task scope and external-action authorization separate from this visual guidance.
