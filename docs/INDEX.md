# docs

| Name | Type | Notes |
| --- | --- | --- |
| `00-jobwatch-architecture.md` | file | Architecture notes for JobWatch. |
| `02-investment-harness.md` | file | Investment harness design notes. |
| `03-log-analysis-company-analysis-2026-04-07.md` | file | Session-log review of company-analysis workflows and CLI opportunities. |
| `04-browser-cli-v2-python-port.md` | file | Combined doc: implementation deep dive of the TS/JS browser-cli-v2 + full Python migration plan. |
| `05-morning-market-brief-cli-gap-analysis.md` | file | V1 implementation plan for the morning market brief pipeline, including CLI commands, storage layout, and scheduler integration. |
| `06-collect-evidence-analyze-business-cli-plan.md` | file | Design doc for a workflow-aware Minerva evidence/analysis layer supporting the `collect-evidence` and `analyze-business` skills. |
| `07-collect-evidence-analyze-business-skill-update-notes.md` | file | Skill update notes for the evidence/analysis workflow. |
| `08-robinhood-session-trace-audit.md` | file | Session trace audit for Robinhood analysis. |
| `09-browser-fallback-improvement-plan.md` | file | Improvement plan: browser-based fallback for Cloudflare-blocked IR feeds and macro sources in the morning brief pipeline. |
| `10-llm-wiki-zettelkasten-design.md` | file | Design synthesis: merging Karpathy's LLM Wiki pattern with the Zettelkasten method into a unified knowledge-base skill. |
| `11-minerva-evidence-starter-live-tested-guide.md` | file | Live-tested starter walkthrough of the current `minerva evidence` workflow, including real command behavior, workflow design, and measurement gaps. |
| `12-minerva-evidence-v2-zero-based-redesign.md` | file | Zero-based redesign for a smaller, more agentic evidence workflow built around `init`, `add-source`, `review`, and `analysis context`. |
| `14-evidence-v2-quickstart.md` | file | Quickstart guide for the V2 evidence workflow: commands, workspace layout, migration, and SEC per-section file notes. |
| `15-collect-evidence-research-upgrade-plan.md` | file | Upgrade plan: rename collect-evidence → research-and-collect, add shared deep-dive checklist, 10 research dimensions, competitive mapping, parallel execution, and structured data build. |

## Notes
- Docs hold higher-level designs, reports, and durable reference writeups.
- The morning-brief doc lives here because it defines the repo-level CLI additions, storage layout, and scheduler integration for the daily pipeline.
- The evidence starter guide documents current behavior as-tested, including places where coverage and inventory count artifacts rather than logical sources.
- The V2 redesign doc is the clean-sheet proposal for replacing deterministic bookkeeping with a smaller agentic interface.
