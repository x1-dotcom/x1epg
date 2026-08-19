# X1 EPG

Modern, validated and automation-first EPG catalogue for the X1 ecosystem.

## Goals

- Canonical channel IDs shared with X1 picons where possible.
- Country-first organisation.
- XMLTV-compatible output.
- Multiple source candidates per channel with explicit priority and fallback.
- Deterministic validation, deduplication and provenance.
- Scheduled refresh with fail-closed publishing.
- Coverage and health reporting.

## Repository layout

- `sources/` — approved EPG source manifests.
- `countries/` — generated per-country XMLTV/catalogue outputs.
- `data/` — canonical indexes, schemas, coverage and runtime reports.
- `tools/` — validation, normalization and generation utilities.
- `.github/workflows/` — scheduled/dispatch automation.

## Canonical channel model

Each channel uses a stable `canonicalId`, country, timezone, language, aliases and optional `piconId`. Source-specific IDs are stored separately so upstream provider changes do not force X1 consumer IDs to change.

## Publication policy

Generated EPG data is only publishable after source validation, channel normalization and catalogue validation complete successfully. Failed refreshes must preserve the last known-good output and publish diagnostics instead of replacing valid data with partial results.

## Initial scope

P1 establishes the repository contract and Portugal bootstrap. Subsequent phases add source ingestion, XMLTV normalization, fallback arbitration, coverage metrics and more countries.
