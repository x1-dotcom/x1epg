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
- Channel-level quality scoring with anti-flap source recommendations.

## Repository layout

- `sources/` — approved EPG source manifests eligible for runtime ingestion/fallback evaluation.
- `countries/` — generated per-country XMLTV/catalogue outputs.
- `data/` — canonical indexes, schemas, candidate registry, coverage and runtime reports.
- `tools/` — validation, normalization, source qualification, comparison, quality and generation utilities.
- `.github/workflows/` — scheduled/dispatch automation.

## Canonical channel model

Each channel uses a stable `canonicalId`, country, timezone, language, aliases and optional `piconId`. Source-specific IDs are stored separately so upstream provider changes do not force X1 consumer IDs to change.

## Source qualification

A public XMLTV URL is not automatically an approved fallback source. New feeds first enter `data/source-candidates.json` and are audited for fetchability, XML validity, channel/programme volume, newest programme timestamp and freshness. Stale candidates are rejected before they can influence fallback arbitration. Promotion into `sources/` is explicit; there is no automatic promotion.

The secondary Portugal candidate `f0nZ/epg-tv-portuguesa` remains useful as channel-ID evidence but the currently observable guide contains 2021 programme timestamps, so X1 treats it as stale rather than a production fallback. EPG.PW remains blocked from automated commercial use pending explicit permission compatible with X1 use.

## Quality engine

`tools/compare_sources.py` compares approved/candidate technical coverage channel by channel. `tools/quality_engine.py` converts that telemetry into advisory recommendations only when minimum future-programme and schedule-horizon thresholds are met. `tools/decision_guard.py` adds stateful anti-flap protection: a different source must win three consecutive observations and respect a 24-hour switch cooldown before it becomes technically switch-eligible.

No quality decision changes source mappings automatically. Technical quality, source approval and redistribution rights remain separate gates.

## Publication policy

Generated EPG data is only publishable after source validation, channel normalization, catalogue validation and explicit redistribution-rights verification complete successfully. Failed refreshes preserve the last known-good output and publish diagnostics instead of replacing valid data with partial or stale results.

## Current scope

P1 established the repository contract. P2 added Portugal and live XMLTV ingestion. P3 added multi-source fallback planning and canonical XMLTV generation with rights gates. P4 added source qualification and freshness auditing. P4.1 added EPGShare01 multi-country qualification. P4.2 defined canonical manifests for Portugal, Spain, France, Germany, Italy, United Kingdom, Switzerland and the Netherlands. P4.3 added EPGShare01 vs dobleM channel-level comparison. P4.4 added advisory quality scoring. P4.5 adds persistent anti-flap decision state with consecutive-win and cooldown guards. Brazil remains candidate-only until its current channel-list/runtime evidence is confirmed.
