# docs

| Name | Type | Notes |
| --- | --- | --- |
| [00-jobwatch-architecture.md](./00-jobwatch-architecture.md) | file | Architecture notes for JobWatch. |
| [02-zettel-wiki-v3-design.md](./02-zettel-wiki-v3-design.md) | file | V3 design notes for the zettel wiki workflow. |
| [05-morning-market-brief-cli-gap-analysis.md](./05-morning-market-brief-cli-gap-analysis.md) | file | V1 implementation plan for the morning market brief pipeline, including CLI commands, storage layout, and scheduler integration. |
| [06-collect-evidence-analyze-business-cli-plan.md](./06-collect-evidence-analyze-business-cli-plan.md) | file | Design doc for a workflow-aware Minerva evidence/analysis layer supporting the `collect-evidence` and `analyze-business` skills. |
| [07-collect-evidence-analyze-business-skill-update-notes.md](./07-collect-evidence-analyze-business-skill-update-notes.md) | file | Skill update notes for the evidence/analysis workflow. |
| [08-robinhood-session-trace-audit.md](./08-robinhood-session-trace-audit.md) | file | Session trace audit for Robinhood analysis. |
| [09-browser-fallback-improvement-plan.md](./09-browser-fallback-improvement-plan.md) | file | Improvement plan for browser-based fallback on Cloudflare-blocked IR feeds and macro sources. |
| [10-llm-wiki-zettelkasten-design.md](./10-llm-wiki-zettelkasten-design.md) | file | Design synthesis combining Karpathy's LLM Wiki pattern with Zettelkasten. |
| [11-minerva-evidence-starter-live-tested-guide.md](./11-minerva-evidence-starter-live-tested-guide.md) | file | Live-tested starter walkthrough of the current `minerva evidence` workflow. |
| [12-minerva-evidence-v2-zero-based-redesign.md](./12-minerva-evidence-v2-zero-based-redesign.md) | file | Zero-based redesign for a smaller, more agentic evidence workflow. |
| [13-zettel-wiki-v2-upgrade-plan.md](./13-zettel-wiki-v2-upgrade-plan.md) | file | Upgrade plan for the zettel wiki workflow. |
| [14-evidence-v2-quickstart.md](./14-evidence-v2-quickstart.md) | file | Quickstart guide for the V2 evidence workflow. |
| [15-collect-evidence-research-upgrade-plan.md](./15-collect-evidence-research-upgrade-plan.md) | file | Upgrade plan for research-and-collect, research dimensions, and structured evidence buildout. |
| [16-analyze-business-wiki-integration-plan.md](./16-analyze-business-wiki-integration-plan.md) | file | Plan for integrating analyze-business workflows with the local wiki. |
| [17-analyze-business-v2-improvement-plan.md](./17-analyze-business-v2-improvement-plan.md) | file | Improvement plan for analyze-business v2 based on Oracle deep-dive trace analysis. |
| [18-minerva-extract-cli-tdd-plan.md](./18-minerva-extract-cli-tdd-plan.md) | file | TDD plan for `minerva extract`, legacy multi-question command removal, and new `extract-files`. |
| [19-bare-invocation-help-plan.md](./19-bare-invocation-help-plan.md) | file | TDD plan: bare `minerva <command>` shows clean help (no error), exit 0. |
| [analysis/](./analysis/INDEX.md) | folder | Trace analyses and deeper implementation reviews. |
| [plans/](./plans/) | folder | Additional planning documents. |

## Notes
- Docs hold higher-level designs, reports, and durable reference writeups.
- The morning-brief doc lives here because it defines the repo-level CLI additions, storage layout, and scheduler integration for the daily pipeline.
- The evidence starter guide documents current behavior as-tested, including places where coverage and inventory count artifacts rather than logical sources.
- The V2 redesign doc is the clean-sheet proposal for replacing deterministic bookkeeping with a smaller agentic interface.
- `18-minerva-extract-cli-tdd-plan.md` is the current plan for fixing the extraction CLI shape before implementation.
