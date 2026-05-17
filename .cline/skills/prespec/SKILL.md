---
name: prespec
description: Normalize raw product intake into a reviewed pre-Spec-Kit requirement baseline. Use when Codex needs to run ADR-0027 Step 1-2 workflows for docs/spec-intake/[feature], run guided full flow, maintain docs/spec-intake/index.md, inspect raw PO material, identify missing product decisions, generate or update product-spec.md, supporting-artifacts/readiness-checks.md, clarification-log.md, scope-decision.md, handoff-checklist.md, or export Spec Kit input packages without creating specs/ artifacts.
---

# Prespec

## Overview

Use this skill to help PO/TPM turn raw product intake into an accepted
`product-spec.md` and one or more Spec Kit input packages under
`docs/spec-intake/[feature]/`. The authoritative workflow is ADR-0027; read
`docs/adr/0027-prespec-workflow.md` before making changes.

## Hard Boundaries

- Do not create, edit, or delete `specs/[feature]/spec.md`.
- Do not write `.specify/feature.json`.
- Do not create or switch branches other than `function/[feature]` during initialization.
  Pass `--no-branch` to `prespec_init.py` if the branch already exists or branch
  creation should be skipped.
- Initialize `function/[feature]` only from `develop`; `prespec_init.py` fetches
  `origin/develop` and rejects stale local bases when the remote is reachable.
- Do not create or switch Spec Kit work branches; those are owned by
  `speckit-specify` and its `before_specify` hook.
- Do not run `speckit-specify`, `speckit-plan`, `speckit-tasks`, or implementation
  skills.
- Do not mark `product-spec.md` as `Accepted` unless PO/TPM acceptance evidence is
  explicitly provided.
- Do not mark any `speckit-input.md` as `Accepted` unless the product baseline is
  accepted and PO/TPM handoff approval is recorded.
- Keep requirements in product/specification language. Avoid implementation tasks
  unless a technical constraint is itself part of the product requirement.

## Automation Resources

Use scripts for deterministic filesystem, index, and validation work. Use Codex
judgment for interpreting raw material, drafting requirements, classifying feature
traits, designing clarification questions, and deciding whether content is product
ready.

Available scripts:

- `.cline/skills/prespec/scripts/prespec_init.py [feature-slug] --po "..." --tpm "..." [--title "..."]`
  creates `docs/spec-intake/index.md` and the feature `raw/` workspace. When raw
  source material already exists, when any pre-spec artifact already exists, or when
  `--with-artifacts` is passed, it also creates missing artifacts from templates
  without overwriting existing files. If `--title` is omitted, it derives a display
  title from the feature slug.
- `.cline/skills/prespec/scripts/prespec_sync_index.py [feature-slug]` synchronizes the global
  `docs/spec-intake/index.md` from `product-spec.md` and
  `handoff-checklist.md`. Omit `[feature-slug]` to rebuild the registry from all
  feature workspaces.
- `.cline/skills/prespec/scripts/prespec_status.py [feature-slug]` reports the current ADR-0027 step,
  current status, completed items, blockers, risks, and recommended next action.
  Omit `[feature-slug]` to summarize the global pre-spec board.
- `.cline/skills/prespec/scripts/prespec_validate.py [feature-slug]` checks mechanical readiness:
  skeleton files, global registry entry, raw source listing, accepted-status evidence,
  blocking clarification markers, readiness-check completeness, and handoff checklist
  consistency.

Templates live under `assets/templates/`. Do not manually recreate template boilerplate
when a script can create it.

## Workspace Resolution

1. Resolve the feature slug:
   - Use the slug supplied by the user if present.
   - If the user asks for the overall pre-spec board, use `docs/spec-intake/index.md`
     and do not choose a feature workspace unless needed.
   - Otherwise, if exactly one directory exists under `docs/spec-intake/`, use it.
   - If multiple feature directories exist and the user did not identify one, ask for
     the feature slug before editing.
2. For feature work, edit only `docs/spec-intake/index.md` and
   `docs/spec-intake/[feature]/`.
3. Preserve user-provided raw material under `raw/`; never rewrite or summarize over
   the original source files.
4. Initialize a feature workspace with `scripts/prespec_init.py`. Before raw source
   material exists, initialization creates only the global registry, feature directory,
   and `raw/` workspace. After raw source material is present, or when
   `--with-artifacts` is passed, it normalizes the full artifact skeleton:

```text
docs/spec-intake/
+-- index.md
+-- [feature]/
|   +-- raw/
```

```text
docs/spec-intake/
+-- index.md
+-- [feature]/
|   +-- raw/
|   +-- intake-index.md
|   +-- extracted-requirements.md
|   +-- clarification-log.md
|   +-- scope-decision.md
|   +-- product-spec.md
|   +-- supporting-artifacts/
|   |   +-- readiness-checks.md
|   |   +-- [artifact].md
|   +-- spec-kit-inputs/
|   |   +-- index.md
|   |   +-- [spec-feature]/
|   |       +-- speckit-input.md
|   +-- handoff-checklist.md
```

## Operating Loop

Run the workflow as an iterative readiness assistant:

```text
User asks for current progress
-> run prespec_status.py

PO adds raw source material
-> run prespec_init.py if the artifact skeleton is missing
-> index sources
-> extract candidate requirements
-> classify feature traits and readiness checks
-> identify missing content, conflicts, and unresolved decisions
-> recommend next actions and ask prioritized blocking questions
-> PO/TPM provides answers or decisions
-> update product-spec.md, supporting artifacts, logs, and handoff status
-> run prespec_sync_index.py
-> run prespec_validate.py
-> repeat until product-spec.md is ready for PO/TPM acceptance
```

## Guided Full Flow Mode

Treat requests such as `run guided full flow`, `continue guided full flow`, or
`run the full guided pre-spec flow` as the standard one-command operator mode after
the feature workspace has been initialized.

In guided full flow:

1. Start by running `scripts/prespec_status.py [feature-slug]`.
2. Normalize missing workspace/artifact skeleton with `scripts/prespec_init.py` when
   allowed by branch rules and existing context. Do not invent PO/TPM names or
   acceptance evidence.
3. Continue through every safe pre-spec action that current inputs allow:
   source indexing, requirement extraction, clarification logging, scope decisions,
   readiness classification, required supporting artifacts, product-spec drafting,
   Spec Kit input package drafting, index sync, validation, and handoff checklist
   updates.
4. Stop at the first product/governance gate that requires user input, and report the
   exact missing input instead of guessing.

Guided full flow must stop and ask for input when any of these gates is reached:

- Raw source material is missing or a raw file cannot be interpreted safely.
- Required PO/TPM clarification decisions are missing.
- Product Owner or TPM identity is missing for approval records.
- `product-spec.md` appears reviewable but lacks durable PO/TPM acceptance evidence.
- Spec Kit input package acceptance or handoff approval is requested without an
  accepted product baseline and explicit PO/TPM handoff approval.
- Required dynamic readiness artifacts cannot be completed from available sources.

Guided full flow may create Draft `speckit-input.md` packages when the product
baseline is clear enough to split into one or more single-feature boundaries. It must
not mark `product-spec.md` or any `speckit-input.md` as `Accepted` without the
evidence required in Hard Boundaries.

End every guided full flow run with:

- Current status and current step.
- Work completed in this run.
- Blocking gates that stopped further progress.
- Exact PO/TPM decisions, evidence, raw files, or approvals needed next.
- The next recommended one-command prompt, usually `Use $prespec for [feature-slug]:
  run guided full flow.` for Codex or `/prespec [feature-slug]: run guided full flow`
  for Claude Code.

Each run must end with a concise readiness summary:

- Current status: `Draft`, `Blocked`, `In Review`, or `Ready for PO/TPM acceptance`.
- Completed items.
- Blocking gaps.
- Non-blocking risks or deferred items.
- Required PO/TPM decisions.
- Recommended next actions.

When the user is unsure what to do next, run `scripts/prespec_status.py` before
editing. Use its output to explain the current step and the next concrete action.

## Artifact Responsibilities

### `docs/spec-intake/index.md`

Maintain the global intake workspace registry. This file tracks all pre-spec
workspaces at summary level only; do not copy raw source details into it.

Include at least:

- Feature slug.
- Title.
- Status: `Draft`, `Blocked`, `In Review`, `Ready`, `Accepted`, or
  `Handoff Complete`.
- PO.
- TPM.
- Product spec link.
- Handoff checklist link.
- Last updated date.
- Short notes about status, blockers, or handoff.

### `docs/spec-intake/[feature]/intake-index.md`

Maintain a source inventory and processing state for the current feature only.
Include at least:

- Source ID.
- File/path or durable reference.
- Source type, such as meeting notes, customer request, screenshot, Slack/email
  summary, existing document, or clarification answer.
- Source date if known.
- Stakeholder or owner if known.
- Processing status: `New`, `Indexed`, `Extracted`, `Needs Review`, or `Resolved`.
- Notes about quality, missing context, or conflicts.

### `extracted-requirements.md`

Extract candidate requirements from raw material. Keep traceability back to source
IDs. Separate:

- Candidate functional requirements.
- Candidate actors and user goals.
- Candidate success criteria.
- Candidate constraints and assumptions.
- Candidate error/failure behavior.
- Duplicate, conflicting, or unclear statements.

### `clarification-log.md`

Track questions and decisions. Every item should identify:

- Question or conflict.
- Source IDs.
- Impact area: scope, actor, workflow, API, integration, data, permission, security,
  error handling, observability, success criteria, or handoff.
- Status: `Open`, `Blocking`, `Answered`, `Non-blocking`, `Deferred`, or
  `Out of Scope`.
- Answer or decision.
- Decision owner and date when available.

Ask no more than five blocking questions per review cycle. Prioritize scope, failure
behavior, external integration, permission/security, and measurable success criteria.

### `scope-decision.md`

Maintain the stable scope boundary:

- MVP in scope.
- Explicitly out of scope.
- Deferred or later.
- Split-feature decisions.
- Cross-feature dependencies and handoff order.
- Decision rationale and source IDs.

### `supporting-artifacts/readiness-checks.md`

Generate or update dynamic readiness checks before accepting `product-spec.md`.
Classify feature traits and record whether each supporting artifact is required,
optional, or N/A. Every N/A entry must include a rationale.

Use these trigger rules:

| Feature trait | Required supporting artifact or section |
|---------------|------------------------------------------|
| Multi-role, multi-system, or multi-step workflow | Workflow diagram or sequence diagram |
| Async job, callback, event handling, or state transition | Sequence diagram and state transition model |
| New or changed external/internal API behavior | API contract or API design note |
| Third-party or cross-system integration | Integration note, data mapping, timeout/retry semantics, and failure behavior |
| New or changed data lifecycle | Data model note, retention rule, migration note, or compatibility note |
| Permission, role, or approval behavior | Permission matrix or approval flow |
| Security, privacy, compliance, or audit concern | Security/privacy requirements and audit expectations |
| Import, export, or batch processing | Validation rules, partial failure policy, and recovery behavior |
| High-risk, irreversible, payment, order, or control flow | Idempotency expectations, compensation behavior, and audit trail requirements |
| Operationally sensitive behavior | Observability, alerting, and manual recovery note |

Required artifacts may be standalone files under `supporting-artifacts/` or clearly
named sections in `product-spec.md`. Use standalone files for diagrams, API contracts,
integration notes, data model notes, permission matrices, error-handling matrices,
and observability/recovery notes when they are non-trivial.

### `product-spec.md`

Draft or refine the PO/TPM-facing requirement baseline. It must include the approval
header:

```markdown
# Product Spec: [Feature Name]

**Status:** Draft | In Review | Accepted
**Feature Slug:** [feature]
**Function Branch:** function/[feature]
**Product Owner:** [name]
**TPM:** [name]
**Accepted At:** YYYY-MM-DD or N/A
**Acceptance Evidence:** [meeting note / PR review / checklist reference]
```

Ensure the content is acceptable only when:

- Problem, goal, target actors, business context, and priority are explicit.
- MVP scope is separated from out-of-scope and deferred work.
- Functional requirements describe product behavior and are testable.
- Acceptance scenarios cover primary paths and relevant exception paths.
- Success criteria are observable or measurable.
- Constraints, assumptions, dependencies, and domain rules are recorded.
- Blocking clarifications are resolved.
- Remaining open items are marked non-blocking, deferred, or out of scope.
- Scope decisions are traceable to sources, clarification answers, or PO/TPM
  decisions.
- Relevant failure behavior is defined, or explicitly marked not applicable.
- The product spec can be split into one or more single-feature Spec Kit inputs.

Include this table in `product-spec.md`:

```markdown
## Required Supporting Artifacts

| Artifact | Required | Status | Link | Rationale |
|----------|----------|--------|------|-----------|
```

### Error Handling

Define product-level failure behavior when relevant. Include:

- Business state after failure: failed, pending, partially complete, rolled back, or
  equivalent.
- User/operator/system feedback.
- Recovery path: retry, edit and resubmit, manual reconciliation, support escalation,
  or equivalent.
- Owner of manual follow-up.
- Audit, notification, and evidence requirements when applicable.

Create an error-handling matrix or equivalent section for integrations, async
processing, state transitions, import/export, batch processing, permission-sensitive
behavior, or high-risk irreversible flows.

### `spec-kit-inputs/`

Create or update Spec Kit input packages only after the product spec has enough
scope clarity to identify one or more single-feature boundaries. A package may stay
`Draft` during review. Only accepted packages may be handed to `speckit-specify`.

Each `spec-kit-inputs/[spec-feature]/speckit-input.md` must be self-contained and
must omit meeting-note noise, rejected options, unresolved contradictions, and
governance history.

Required structure:

```markdown
# Spec Kit Input: [Spec Feature Name]

**Status:** Draft | Accepted
**Source Product Spec:** ../../product-spec.md
**Source Scope Decision:** ../../scope-decision.md
**Spec Feature Slug:** [spec-feature]
**Handoff Order:** [number]

## Feature Summary
## Actors
## Problem and Goal
## In Scope
## Out of Scope
## User Scenarios
## Functional Requirements
## Success Criteria
## Constraints and Assumptions
## Source Decisions
```

Maintain `spec-kit-inputs/index.md` with package slug, status, scope summary,
dependencies, source decisions, and handoff order.

### `handoff-checklist.md`

Maintain the Step 2 readiness gate. Set:

- `Status: Draft` while work is ongoing.
- `Status: Blocked` when any blocking clarification or required dynamic readiness
  check remains incomplete.
- `Status: Ready` only when every checkbox outside Notes is complete and accepted
  input packages are ready for `speckit-specify`.

## Validation Before Reporting

Before ending a run:

1. Run `scripts/prespec_sync_index.py [feature-slug]`.
2. Run `scripts/prespec_validate.py [feature-slug]`. A newly initialized workspace
   with no raw source material may report that the artifact skeleton is deferred; this
   is valid until PO adds source files under `raw/`.
3. Confirm no protected Spec Kit artifacts were created or modified.
4. Confirm raw source files were not rewritten.
5. Confirm `docs/spec-intake/index.md` lists the feature workspace at summary level
   and does not duplicate raw source details.
6. Confirm every raw source for the feature is listed in
   `docs/spec-intake/[feature]/intake-index.md`.
7. Confirm every generated statement in `product-spec.md` is traceable to a source,
   clarification answer, explicit assumption, or PO/TPM decision.
8. Confirm `readiness-checks.md` records required, optional, and N/A supporting
   artifacts with rationales.
9. Confirm all blocking gaps are reflected in `clarification-log.md` and
   `handoff-checklist.md`.
10. Confirm accepted statuses are not used without durable PO/TPM evidence.

Report changed files, current readiness status, blocking gaps, and recommended next
actions.

## Post-Execution Checks

**Check for extension hooks (after clarification)**:
Check if `.specify/extensions.yml` exists in the project root.
- If it exists, read it and look for entries under the `hooks.after_clarify` key
- If the YAML cannot be parsed or is invalid, skip hook checking silently and continue normally
- Filter out hooks where `enabled` is explicitly `false`. Treat hooks without an `enabled` field as enabled by default.
- For each remaining hook, do **not** attempt to interpret or evaluate hook `condition` expressions:
  - If the hook has no `condition` field, or it is null/empty, treat the hook as executable
  - If the hook defines a non-empty `condition`, skip the hook and leave condition evaluation to the HookExecutor implementation
- When constructing slash commands from hook command names, replace dots (`.`) with hyphens (`-`). For example, `speckit.git.commit` → `/speckit-git-commit`.
- For each executable hook, output the following based on its `optional` flag:
  - **Optional hook** (`optional: true`):
    ```
    ## Extension Hooks

    **Optional Hook**: {extension}
    Command: `/{command}`
    Description: {description}

    Prompt: {prompt}
    To execute: `/{command}`
    ```
  - **Mandatory hook** (`optional: false`):
    ```
    ## Extension Hooks

    **Automatic Hook**: {extension}
    Executing: `/{command}`
    EXECUTE_COMMAND: {command}
    ```
- If no hooks are registered or `.specify/extensions.yml` does not exist, skip silently