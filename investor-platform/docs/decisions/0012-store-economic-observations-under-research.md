# 0012. Store economic observations under Research

## Status

Proposed

## Context

Economic reports need repeatable public-source collection, source evidence and clear charts. Portfolio transactions and replaceable security-price caches do not provide that contract. The first sources are BLS food prices, USDA food-plan costs and EIA fuel prices. The extension adds broad macroeconomic measures, published Shiller CAPE and a defined quarterly public-equity/GDP proxy. Their publication schedules differ, and some of their history can change. Other article sources do not yet have confirmed permitted feeds.

The initial research suggested separate source, series, snapshot and observation tables and a top-level Data page. The implementation request instead calls for a minimal database, platform-managed collection and an Economics subsection under Research. Static catalog tables and a general scheduling service would add maintenance without a current use case.

## Decision

Keep Economics within Research and use the existing PostgreSQL, FastAPI and React projects. Keep source and series definitions in one typed code registry. Persist only append-only observation changes and one durable collection-state record per source and workspace. Preserve original downloaded files by content hash in ignored local storage; each accepted observation retains its safe source location, hash and parser provenance.

Collection validates a complete candidate source batch before admission. Repeated imports add no unchanged facts. Corrections append versions; failures retain accepted values. The default display uses the latest accepted current-feed facts. This is our collected history, not a reconstruction of what was published before collection began. Derived family food costs retain their exact component observations and stated household composition.

Let a small Economics worker run within the platform's existing application lifetime. It owns source-specific due times, bounded retry and restart state. Source publication frequency and collection check frequency remain separate explicit values. Keep collection outside chart reads, separate from security-price collection, and behind the platform's existing workspace access boundary.

Use original publisher downloads when a distribution service does not provide clear permission for database storage. A free public download or API key alone does not establish that permission.

Keep accepted source levels separate from bounded display calculations. Calculate named growth rates, job changes and the public-equity/GDP proxy from exact stored input versions. Keep both policy-rate bounds, retain signed economic values, and preserve missing calendar periods. Published CAPE remains a monthly publisher series, including any provisional source notes; the quarterly equity/GDP ratio remains a clearly named proxy rather than a daily market reading.

Start with verified BLS, USDA and EIA sources. Give substitutes their own identities and label their measurement limits. Keep other sources unavailable until access, definition and permitted use are confirmed. Show actual observation periods, units, source notes and missing points in the interface.

## Consequences

The database stays small and avoids duplicate static definitions. Collection can recover after restart, repeated downloads remain safe and earlier changed values remain traceable. Research gains an independent economics view without changing portfolio ownership or ledger behavior.

Changing definitions requires a reviewed code change rather than a database catalog edit. Raw evidence needs a backup alongside PostgreSQL. Local file storage and an in-process worker require the platform host to remain available; this does not provide a distributed scheduler or a complete historical release archive. Provider timestamps and reuse rights remain source-specific limits.

## Related ADRs

```text
[ADR-0012: Store economic observations under Research]
      |
      +-- Relates to --> [ADR-0001: Documentation and pages] - Place economics inside Research.
      +-- Relates to --> [ADR-0008: Store annual financial observations] - Retain exact source evidence and immutable changed facts in a separate domain.
      +-- Relates to --> [ADR-0011: Group code by feature and share calculation rules] - Keep economics collection, contracts and chart rules together.
```
