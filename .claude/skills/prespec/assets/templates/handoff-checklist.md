# Pre-Spec Handoff Checklist: {{FEATURE_TITLE}}

**Feature Slug:** {{FEATURE_SLUG}}
**Product Spec:** product-spec.md
**Spec Kit Inputs Index:** spec-kit-inputs/index.md
**Status:** Draft

## Product Baseline

- [ ] `docs/spec-intake/index.md` lists this feature workspace
- [ ] `product-spec.md` status is `Accepted`
- [ ] PO and TPM approval are recorded in `product-spec.md`
- [ ] All raw source material for this feature is listed in `intake-index.md`
- [ ] Blocking questions in `clarification-log.md` are resolved
- [ ] In-scope and out-of-scope decisions are recorded in `scope-decision.md`
- [ ] `product-spec.md` includes the required supporting-artifact summary
- [ ] Relevant failure behavior is defined, or explicitly marked not applicable

## Dynamic Readiness Checks

- [ ] `supporting-artifacts/readiness-checks.md` has been generated
- [ ] Feature traits and required supporting artifacts are recorded
- [ ] Every required supporting artifact is complete and linked from `product-spec.md`
- [ ] Every not-applicable artifact has an explicit rationale
- [ ] Error-handling matrix or equivalent section is complete when required

## Spec Kit Input Packages

- [ ] `spec-kit-inputs/index.md` lists every generated input package
- [ ] Each input package has exactly one Spec Kit feature boundary
- [ ] Each accepted `speckit-input.md` has `Status: Accepted`
- [ ] Each accepted `speckit-input.md` links back to source decisions
- [ ] Handoff order is recorded for accepted input packages

## Handoff Approval

- [ ] TPM confirms accepted input packages are ready for `speckit-specify`
- [ ] PO confirms the split from product spec to Spec Kit inputs is acceptable
- [ ] No accepted input contains unresolved contradictions or meeting-note noise

## Notes

- TBD
