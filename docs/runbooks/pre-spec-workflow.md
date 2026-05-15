# Pre-Spec Workflow Runbook

This runbook explains how PO/TPM use the pre-spec skill to turn raw product intake into an
accepted `product-spec.md` and one or more Spec Kit input packages.

Decision source: [ADR-0027](../adr/0027-prespec-workflow.md).

## Who Uses This

- PO uses this flow to provide the feature slug, business context, and raw source
  material.
- TPM uses this flow to operate the pre-spec skill, resolve clarifications, and approve
  handoff readiness.
- RD starts after this flow, when accepted `speckit-input.md` packages are ready for
  `speckit-specify`.

## Simple Operating Model

For day-to-day use, PO/TPM do not need to manually drive each pre-spec checkpoint.
Use this sequence:

1. Initialize the feature intake workspace once with PO and TPM owners.

   Claude Code:

   ```text
   /prespec initialize <feature-slug>
   PO = <po-name>
   TPM = <tpm-name>
   ```

   Codex:

   ```text
   Use $prespec for <feature-slug>: initialize the intake workspace.
   PO = <po-name>
   TPM = <tpm-name>
   ```

   CLINE (Gemma-4-31B):

   ```text
   @prespec initialize <feature-slug>
   PO = <po-name>
   TPM = <tpm-name>
   ```

2. Put raw source material under `docs/spec-intake/<feature-slug>/raw/`.
3. Keep running guided full flow until the skill reports handoff readiness.

Codex guided command:

```text
Use $prespec for <feature-slug>: run guided full flow.
```

Claude Code guided command:

```text
/prespec <feature-slug>: run guided full flow
```

CLINE (Gemma-4-31B) guided command:

```text
@prespec <feature-slug>: run guided full flow
```

When guided full flow reaches a gate, it stops and tells PO/TPM exactly what is
missing, such as raw files, clarification decisions, acceptance evidence, or handoff
approval. Provide the missing input, then run the same guided full flow command again.

The short version is:

```text
Initialize once with PO/TPM -> add raw -> rerun guided full flow until ready
```

## Agent Invocation

The pre-spec skill is invoked differently depending on which AI agent you are using.

### Claude Code

Use the `/prespec` slash command:

```text
/prespec <feature-slug>: <what you want to do>
```

Common requests:

```text
/prespec initialize <feature-slug>
PO = <po-name>
TPM = <tpm-name>
```

```text
/prespec check the current status of <feature-slug>
```

Recommended after initialization:

```text
/prespec <feature-slug>: run guided full flow
```

Targeted requests are still available when needed:

```text
/prespec process raw material for <feature-slug> and tell us what is missing
```

```text
/prespec update <feature-slug> based on these PO/TPM decisions: ...
```

```text
/prespec prepare Spec Kit input packages for <feature-slug>
```

```text
/prespec check whether <feature-slug> is ready for Spec Kit handoff
```

### Codex

Use the `$prespec` variable syntax:

```text
Use $prespec for <feature-slug>: <what you want to do>.
```

Common requests:

```text
Use $prespec for <feature-slug>: initialize the intake workspace.
PO = <po-name>
TPM = <tpm-name>
```

```text
Use $prespec to check the current status of <feature-slug>.
```

```text
Use $prespec to process raw material for <feature-slug> and tell us what is missing.
```

Recommended after initialization:

```text
Use $prespec for <feature-slug>: run guided full flow.
```

Targeted requests are still available when needed:

```text
Use $prespec to update <feature-slug> based on these PO/TPM decisions: ...
```

```text
Use $prespec to prepare Spec Kit input packages for <feature-slug>.
```

```text
Use $prespec to check whether <feature-slug> is ready for Spec Kit handoff.
```

### CLINE (Gemma-4-31B)

Use the `@prespec` mention syntax:

```text
@prespec <feature-slug>: <what you want to do>
```

Common requests:

```text
@prespec initialize <feature-slug>
PO = <po-name>
TPM = <tpm-name>
```

```text
@prespec check the current status of <feature-slug>
```

Recommended after initialization:

```text
@prespec <feature-slug>: run guided full flow
```

Targeted requests are still available when needed:

```text
@prespec process raw material for <feature-slug> and tell us what is missing
```

```text
@prespec update <feature-slug> based on these PO/TPM decisions: ...
```

```text
@prespec prepare Spec Kit input packages for <feature-slug>
```

```text
@prespec check whether <feature-slug> is ready for Spec Kit handoff
```

## Guided Full Flow Details

Use guided full flow when a feature needs to move from raw intake through
product-spec acceptance and then into Spec Kit input packages. After initialization,
the normal operating command is:

```text
Use $prespec for <feature-slug>: run guided full flow.
```

The skill performs every safe pre-spec action available from the current state. When
it reaches a gate that needs PO/TPM input, it stops and lists the exact missing
decisions, evidence, raw files, or approvals. After you provide the missing input, run
the same command again.

For teams that want to understand what the guided command is doing, the underlying
checkpoints are:

1. Initialize the intake workspace once.

```text
Use $prespec for <feature-slug>: initialize the intake workspace.
PO = <po-name>
TPM = <tpm-name>
```

2. PO adds raw files under `docs/spec-intake/<feature-slug>/raw/`.
3. Guided full flow indexes sources, extracts requirements, classifies readiness,
   drafts required supporting artifacts, updates product-spec.md, and maintains the
   handoff checklist as far as current inputs allow.
4. If guided full flow reports missing PO/TPM decisions, provide those decisions in
   the conversation or durable notes, then run guided full flow again.
5. When `product-spec.md` is ready for review, PO/TPM review it and provide durable
   acceptance evidence only after they approve it.
6. After product-spec acceptance evidence is recorded, guided full flow prepares Spec
   Kit input packages and checks handoff readiness.

The pre-spec flow is complete only when `product-spec.md` is `Accepted`, required
readiness checks are complete, accepted `speckit-input.md` packages exist, and
`handoff-checklist.md` is `Ready`. After that, TPM runs `speckit-specify` once per
accepted input package.

## Step 0: Collect Raw Material

PO collects initial requirement material:

- Meeting notes.
- Customer requests.
- Screenshots or screen recordings.
- Slack/email summaries.
- Existing documents.
- Business context, priority, timing, target users, and known constraints.

Do not clean up the raw material by overwriting it. Raw material should remain
traceable.

## Step 1: Create Function Workspace

Make sure you are on the `develop` branch and it is up to date, then ask the AI agent to
initialize (see [Agent Invocation](#agent-invocation) for syntax per agent):

```text
initialize <feature-slug>
PO = <po-name>
TPM = <tpm-name>
```

The display title is derived from `<feature-slug>` by default. Provide an explicit
title only when the official product name must differ from the slug-derived title.

The pre-spec skill automatically:

1. Verifies the current branch is `develop` and checks it against `origin/develop`
   when the remote is reachable.
2. Creates and switches to `function/<feature-slug>`.
3. Creates the global registry entry and the feature `raw/` workspace.

If you are already on the correct `function/<feature-slug>` branch, the skill skips
branch creation and only initializes the workspace. If you need to skip branch
creation for any other reason, pass `--no-branch` to `prespec_init.py` directly.

The pre-spec skill creates or updates:

```text
docs/spec-intake/index.md
docs/spec-intake/<feature-slug>/
docs/spec-intake/<feature-slug>/raw/
```

After initialization, PO puts raw files under:

```text
docs/spec-intake/<feature-slug>/raw/
```

The full pre-spec artifact skeleton is intentionally deferred until raw source
material exists. After PO adds raw files, rerun the initialize request or call
`prespec_init.py` again; it will then create missing artifacts from templates without
overwriting existing files. If a team needs the full skeleton before raw files are
available, pass `--with-artifacts` to `prespec_init.py` directly.

## Step 2: Ask For Current Status

PO/TPM do not need to know the exact workflow step. Ask the AI agent to check the
current status of `<feature-slug>`.

The pre-spec skill reports:

- Current Step.
- Current Status.
- Completed items.
- Blocking gaps.
- Non-blocking risks.
- Recommended next step.

If the team wants a board-level summary, ask the AI agent to show the current pre-spec board.

## Step 3: Normalize Intake And Extract Requirements

Ask the AI agent to process raw material for `<feature-slug>`, update the intake
artifacts, and report what is missing.

The pre-spec skill updates:

```text
docs/spec-intake/index.md
docs/spec-intake/<feature-slug>/intake-index.md
docs/spec-intake/<feature-slug>/extracted-requirements.md
docs/spec-intake/<feature-slug>/clarification-log.md
docs/spec-intake/<feature-slug>/scope-decision.md
docs/spec-intake/<feature-slug>/supporting-artifacts/readiness-checks.md
docs/spec-intake/<feature-slug>/product-spec.md
docs/spec-intake/<feature-slug>/handoff-checklist.md
```

## Step 4: Resolve Clarifications

When the pre-spec skill reports blocking questions, PO/TPM answer them in the
conversation or through durable notes.

Then ask the AI agent to update `<feature-slug>` based on the decisions:

```text
- <decision 1>
- <decision 2>
```

Repeat status checks and clarification updates until no blocking clarification remains.

## Step 5: Review Product Spec

When the pre-spec skill reports that `product-spec.md` is ready for review, PO/TPM review:

```text
docs/spec-intake/<feature-slug>/product-spec.md
```

Before acceptance, confirm:

- Problem, goal, actors, business context, and priority are explicit.
- MVP scope is separated from out-of-scope and deferred work.
- Functional requirements are product behavior, not implementation tasks.
- Acceptance scenarios include primary paths and relevant exception paths.
- Success criteria are observable or measurable.
- Dynamic readiness checks are complete.
- Error handling is defined or explicitly not applicable.
- No blocking clarification remains open.

## Step 6: Accept Product Spec

Only PO/TPM acceptance evidence can move the product spec to `Accepted`.

Ask the AI agent to record PO/TPM acceptance for `<feature-slug>`:

```text
Accepted at = <YYYY-MM-DD>
Acceptance evidence = <meeting note / PR review / checklist reference>
```

The pre-spec skill may then update:

```markdown
**Status:** Accepted
**Accepted At:** <YYYY-MM-DD>
**Acceptance Evidence:** <durable evidence>
```

## Step 7: Prepare Spec Kit Inputs

Ask the AI agent to prepare Spec Kit input packages for `<feature-slug>`.

Each package lives under:

```text
docs/spec-intake/<feature-slug>/spec-kit-inputs/<spec-feature>/speckit-input.md
```

Each accepted input must describe exactly one Spec Kit feature boundary.

## Step 8: Check Handoff Readiness

Ask the AI agent to check whether `<feature-slug>` is ready for Spec Kit handoff.

Handoff is ready only when:

- `product-spec.md` is `Accepted`.
- Required dynamic readiness checks are complete.
- Required supporting artifacts are complete or validly marked N/A.
- Accepted `speckit-input.md` packages exist.
- `handoff-checklist.md` is `Ready`.
- Handoff approval items are checked.

## Step 9: Hand Off To Spec Kit

After the pre-spec skill reports ready for Step 3, TPM runs `speckit-specify` once per
accepted input package.

Input path:

```text
docs/spec-intake/<feature-slug>/spec-kit-inputs/<spec-feature>/speckit-input.md
```

The pre-spec skill stops here. It must not create `specs/[feature]/spec.md`, write
`.specify/feature.json`, or create/switch Spec Kit work branches.

## Automation Notes

These commands are internal helpers. PO/TPM normally ask the AI agent to run the
pre-spec skill instead of running these directly.

### Claude Code

```powershell
python .claude\skills\prespec\scripts\prespec_init.py <feature-slug> --po "<po-name>" --tpm "<tpm-name>"
python .claude\skills\prespec\scripts\prespec_status.py <feature-slug>
python .claude\skills\prespec\scripts\prespec_sync_index.py <feature-slug>
python .claude\skills\prespec\scripts\prespec_validate.py <feature-slug>
```

### Codex

```powershell
python .agents\skills\prespec\scripts\prespec_init.py <feature-slug> --po "<po-name>" --tpm "<tpm-name>"
python .agents\skills\prespec\scripts\prespec_status.py <feature-slug>
python .agents\skills\prespec\scripts\prespec_sync_index.py <feature-slug>
python .agents\skills\prespec\scripts\prespec_validate.py <feature-slug>
```

### CLINE (Gemma-4-31B)

```powershell
python .cline\skills\prespec\scripts\prespec_init.py <feature-slug> --po "<po-name>" --tpm "<tpm-name>"
python .cline\skills\prespec\scripts\prespec_status.py <feature-slug>
python .cline\skills\prespec\scripts\prespec_sync_index.py <feature-slug>
python .cline\skills\prespec\scripts\prespec_validate.py <feature-slug>
```
