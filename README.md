<p align="center">
  <img src="./assets/x1-epg-control.svg" alt="X1 EPG Control" width="100%" />
</p>

<p align="center">
  <strong>X1 EPG is a validation-first XMLTV control system for the X1 ecosystem.</strong><br>
  Canonical IDs · multi-country catalogues · source qualification · last-known-good preservation · provenance · integrity controls
</p>

---

## What X1 EPG is

X1 EPG is not a static list of channels and it is not a blind XMLTV mirror.

It is designed to ingest external programme data, validate it, normalize it into stable X1 channel identities, evaluate source quality, preserve the last-known-good state when refreshes fail, and produce forensic evidence about what was observed.

The project deliberately keeps three decisions separate:

**technical quality**, **source approval**, and **redistribution rights**.

A source can be technically excellent and still remain blocked from publication if redistribution permission is not proven.

<p align="center">
  <img src="./assets/x1-epg-pipeline.svg" alt="X1 EPG data path" width="100%" />
</p>

---

## Current public scope

Canonical manifests currently exist for:

`PT` Portugal · `ES` Spain · `FR` France · `DE` Germany · `IT` Italy · `GB` United Kingdom · `CH` Switzerland · `NL` Netherlands

Brazil remains candidate-oriented pending the same qualification discipline applied to the currently approved country manifests.

Channel identity is country-first and uses stable `canonicalId` values. Where possible, X1 EPG aligns channel identities with the X1 picon catalogue without coupling runtime behaviour to upstream provider naming.

---

## Runtime safety model

The runtime tooling is built to fail closed rather than silently degrade data quality.

Key controls include:

- strict XMLTV timestamps with explicit timezone offsets;
- exact upstream channel-ID preflight checks;
- bounded HTTPS fetching with size limits, redirect policy and private-network / SSRF protection;
- source freshness checks;
- deterministic deduplication and sorting;
- no fuzzy automatic remapping of missing channel IDs;
- no automatic candidate promotion;
- advisory quality recommendations with anti-flap protection;
- failure forensics with stable issue classification;
- last-known-good promotion and rollback protection.

A failed refresh is not treated as permission to replace a valid catalogue with partial, stale or structurally invalid data.

---

## Last Known Good

X1 EPG separates **candidate output** from **active trusted output**.

The pipeline can build a new index, but that index is not promoted simply because a build command completed. Runtime validation and policy gates decide whether it becomes the new last-known-good state.

If validation fails, the previous accepted state is preserved.

This distinction is intentional:

> **BUILD ≠ ACTIVE**

---

## Provenance and integrity

The repository includes tooling to record run provenance and produce tamper-evident integrity evidence around accepted state.

The current source implementation includes:

- run identity and manifest inventory;
- upstream artefact digests;
- output digests;
- last-known-good decision evidence;
- chained integrity records;
- Ed25519 signing support prepared for operational key provisioning;
- key-rotation policy tooling;
- external-anchor contract tooling.

These mechanisms prove observed bytes and state transitions. They do not grant content rights and they do not turn unverified runtime execution into a production-success claim.

Operational signing remains dependent on approved X1 key provisioning. External anchoring remains dependent on a configured external trust service.

---

<p align="center">
  <img src="./assets/x1-epg-trust.svg" alt="X1 EPG trust and publication boundary" width="100%" />
</p>

## Publication policy

X1 EPG treats public availability and redistribution permission as different things.

The current known source posture is conservative:

- EPGShare01 can be technically ingested and evaluated, but explicit redistribution rights have not been proven for X1 publication;
- dobleM remains candidate / qualification material unless explicitly approved and rights-compatible;
- EPG.PW is not treated as an automatically usable commercial redistribution source;
- stale or historically useful feeds may remain useful as channel-ID evidence without becoming production fallbacks.

Therefore:

> **Ingest can be allowed while publish remains blocked.**

Public XMLTV output must remain fail-closed until the selected source is technically valid **and** publication rights are proven compatible with X1 use.

---

## Repository layout

```text
sources/             approved source manifests
countries/           per-country generated/catalogue outputs
data/                indexes, schemas, evidence and runtime reports
tools/               validators, qualification, quality, provenance and safety tooling
tests/               deterministic tooling tests
.github/workflows/   scheduled and manually dispatched validation/sync workflows
```

---

## Core tools

The public tooling includes components for:

`validate_sources` · `validate_channel_lists` · `sync_epg` · `build_index` · `global_validate` · `catalog_coverage` · `compare_sources` · `quality_engine` · `decision_guard` · `runtime_failure_forensics` · `lkg_guard` · `run_provenance` · `integrity_chain` · signed provenance / rotation / anchor support

The exact runtime state of a workflow is not inferred from source code. Source implementation, tests, CI execution and production behaviour remain distinct evidence classes.

---

## Engineering rules

**EXACT IDS OVER GUESSING** · **LKG OVER BAD REFRESHES** · **STRICT TIMEZONES** · **BOUNDED NETWORK I/O** · **NO AUTO-PROMOTION** · **PROVENANCE OVER ASSUMPTION** · **RIGHTS FAIL CLOSED**

---

## X1 ecosystem

X1 EPG is part of the public X1 tooling family and is designed to interoperate cleanly with other X1 projects such as the picon catalogue while preserving explicit system boundaries.

For the wider X1 ecosystem, visit:

- [X1 GitHub profile](https://github.com/x1-dotcom)
- [X1 Picons](https://github.com/x1-dotcom/picons)
- [X1 Community Forum](https://forum.x1panel.space)

---

<p align="center">
  <strong>VALIDATE WHAT YOU INGEST.</strong><br>
  <strong>PRESERVE WHAT YOU TRUST.</strong><br>
  <strong>PUBLISH ONLY WHAT YOU ARE ALLOWED TO REDISTRIBUTE.</strong><br><br>
  <strong>X1 // EPG CONTROL</strong>
</p>

<p align="center">
  © 2026 X1Tech Solutions SA. All Rights Reserved.
</p>
