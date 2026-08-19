# X1 EPG

Modern, validated and automation-first EPG catalogue for the X1 ecosystem.

## Goals

- Canonical channel IDs shared with X1 picons where possible.
- Country-first organisation.
- XMLTV-compatible output.
- Multiple source candidates per channel with explicit priority and fallback.
- Deterministic validation, deduplication and provenance.
- Scheduled refresh with fail-closed publishing.
- Coverage, freshness and health reporting.

## Repository layout

- `sources/` — approved EPG source manifests eligible for runtime ingestion/fallback evaluation.
- `countries/` — generated per-country XMLTV/catalogue outputs.
- `data/` — canonical indexes, schemas, candidate registry, coverage and runtime reports.
- `tools/` — validation, normalization, source qualification and generation utilities.
- `.github/workflows/` — scheduled/dispatch automation.

## Canonical channel model

Each channel uses a stable `canonicalId`, country, timezone, language, aliases and optional `piconId`. Source-specific IDs are stored separately so upstream provider changes do not force X1 consumer IDs to change.

## Source qualification

A public XMLTV URL is not automatically an approved fallback source. New feeds first enter `data/source-candidates.json` and are audited for fetchability, XML validity, channel/programme volume, newest programme timestamp and freshness. Stale candidates are rejected before they can influence fallback arbitration. Promotion into `sources/` is explicit; there is no automatic promotion.

The first secondary Portugal candidate evaluated is `f0nZ/epg-tv-portuguesa`. It is useful as evidence and channel-ID reference, but the currently observable guide contains programme timestamps from 2021, so X1 treats it as a stale candidate rather than a production fallback. The repository also exposes no explicit licence in the current repository view, therefore public redistribution remains blocked.

## Publication policy

Generated EPG data is only publishable after source validation, channel normalization, catalogue validation and explicit redistribution-rights verification complete successfully. Failed refreshes preserve the last known-good output and publish diagnostics instead of replacing valid data with partial or stale results.

## Current scope

P1 established the repository contract. P2 added Portugal and live XMLTV ingestion. P3 added multi-source fallback planning and canonical XMLTV generation with rights gates. P4 adds source qualification, freshness auditing and rejection of stale secondary feeds before they can enter the approved fallback pool.
