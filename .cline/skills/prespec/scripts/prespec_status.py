#!/usr/bin/env python3
"""Report the current ADR-0027 pre-spec step and next action."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys


REQUIRED_FILES = [
    "intake-index.md",
    "extracted-requirements.md",
    "clarification-log.md",
    "scope-decision.md",
    "product-spec.md",
    "supporting-artifacts/readiness-checks.md",
    "spec-kit-inputs/index.md",
    "handoff-checklist.md",
]

RAW_PLACEHOLDER_FILES = {".gitkeep"}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def extract_field(text: str, field: str, default: str = "") -> str:
    match = re.search(rf"^\*\*{re.escape(field)}:\*\*\s*(.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else default


def validate_slug(slug: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", slug):
        raise ValueError("feature slug must use letters, digits, dot, underscore, or hyphen")
    if ".." in slug or "/" in slug or "\\" in slug:
        raise ValueError("feature slug must not contain path traversal or path separators")
    return slug


def raw_files(feature_dir: Path) -> list[str]:
    raw_dir = feature_dir / "raw"
    if not raw_dir.exists():
        return []
    return sorted(
        path.relative_to(feature_dir).as_posix()
        for path in raw_dir.rglob("*")
        if path.is_file() and path.name not in RAW_PLACEHOLDER_FILES
    )


def unchecked_checkboxes(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip().startswith("- [ ]")]


def table_rows(text: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in text.splitlines():
        if not line.startswith("|") or "---" in line:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        rows.append(cells)
    return rows


def count_status_rows(text: str, status: str) -> int:
    target = status.lower()
    count = 0
    for cells in table_rows(text):
        if any(cell.lower() == target for cell in cells):
            count += 1
    return count


def readiness_gaps(readiness: str) -> list[str]:
    gaps: list[str] = []
    for cells in table_rows(readiness):
        if not cells or cells[0] == "Feature Trait" or len(cells) < 6:
            continue
        trait, detected, status, rationale = cells[0], cells[1].lower(), cells[3].lower(), cells[5].lower()
        if detected in {"yes", "required", "true"} and status != "complete":
            gaps.append(f"{trait}: required artifact is not complete")
        elif status == "n/a" and rationale in {"", "tbd", "n/a"}:
            gaps.append(f"{trait}: N/A rationale is missing")
    return gaps


def accepted_speckit_inputs(feature_dir: Path) -> list[Path]:
    accepted: list[Path] = []
    for path in (feature_dir / "spec-kit-inputs").glob("*/speckit-input.md"):
        if extract_field(read_text(path), "Status", "Draft") == "Accepted":
            accepted.append(path)
    return sorted(accepted)


def has_registry_entry(index_text: str, slug: str) -> bool:
    return any(row and row[0] == slug for row in table_rows(index_text))


def print_list(title: str, items: list[str]) -> None:
    print(f"{title}:")
    if not items:
        print("- None")
        return
    for item in items:
        print(f"- {item}")


def report_board(intake_root: Path) -> int:
    index_path = intake_root / "index.md"
    if not index_path.exists():
        print("Current Step: Step 1 - Initialize pre-spec registry")
        print("Current Status: Missing global registry")
        print("Recommended Next Step: Ask the AI agent to initialize a feature intake workspace.")
        return 1

    feature_dirs = sorted(path for path in intake_root.iterdir() if path.is_dir())
    print("Current Step: Pre-Spec Board Review")
    print(f"Current Status: {len(feature_dirs)} feature workspace(s)")
    print(f"Global Index: {index_path.as_posix()}")
    if not feature_dirs:
        print("Recommended Next Step: Ask the AI agent to initialize the first feature intake workspace.")
        return 0
    print("Feature Workspaces:")
    for path in feature_dirs:
        print(f"- {path.name}")
    print("Recommended Next Step: Run status with a feature slug to see exact blockers.")
    return 0


def status_for_feature(intake_root: Path, slug: str) -> int:
    feature_dir = intake_root / slug
    completed: list[str] = []
    blocking: list[str] = []
    risks: list[str] = []
    next_action = "Continue the pre-spec readiness review."
    primary_step: str | None = None
    review_step: str | None = None

    def mark_blocker(step: str, action: str) -> None:
        nonlocal primary_step, next_action
        if primary_step is None:
            primary_step = step
            next_action = action

    if not intake_root.exists() or not (intake_root / "index.md").exists():
        print("Current Step: Step 1 - Initialize pre-spec registry")
        print("Current Status: Missing global registry")
        print(f"Recommended Next Step: Ask the AI agent to initialize `{slug}`.")
        return 1

    if not feature_dir.exists():
        print("Current Step: Step 1 - Create feature intake workspace")
        print("Current Status: Feature workspace missing")
        print(f"Recommended Next Step: Ask the AI agent to initialize `{slug}`.")
        return 1

    index_text = read_text(intake_root / "index.md")
    if has_registry_entry(index_text, slug):
        completed.append("Global registry lists this feature workspace")
    else:
        blocking.append("Global registry does not list this feature workspace")

    raw = raw_files(feature_dir)
    missing_files = [relative for relative in REQUIRED_FILES if not (feature_dir / relative).exists()]
    if not raw and missing_files:
        completed.append("Feature intake workspace exists")
        blocking.append("No raw source material found under raw/")
        current_step = "Step 0-1 - Intake Collection"
        current_status = "Blocked"
        next_action = "Ask PO to add raw source material under raw/. Then rerun prespec_init.py to create the artifact skeleton."
        return print_feature_report(current_step, current_status, completed, blocking, risks, next_action)

    if missing_files:
        blocking.extend(f"Missing required file: {relative}" for relative in missing_files)
        current_step = "Step 1 - Workspace Initialization"
        current_status = "Blocked"
        next_action = "Ask the AI agent to run prespec_init.py to normalize the workspace skeleton."
        return print_feature_report(current_step, current_status, completed, blocking, risks, next_action)
    completed.append("Required pre-spec artifact skeleton exists")

    intake_index = read_text(feature_dir / "intake-index.md")
    unlisted_raw = [path for path in raw if path not in intake_index]
    if not raw:
        blocking.append("No raw source material found under raw/")
        mark_blocker("Step 0-1 - Intake Collection", "Ask PO to add raw source material under raw/.")
    elif unlisted_raw:
        blocking.extend(f"Raw source not listed in intake-index.md: {path}" for path in unlisted_raw)
        mark_blocker(
            "Step 2 - Source Indexing",
            "Update intake-index.md so every raw source has a source ID and status.",
        )
    else:
        completed.append("Raw source material is indexed")
        review_step = "Step 2 - Requirement Readiness Review"

    extracted = read_text(feature_dir / "extracted-requirements.md")
    if "TBD" in extracted:
        blocking.append("extracted-requirements.md still contains TBD placeholders")
        mark_blocker(
            "Step 2 - Requirement Extraction",
            "Extract candidate requirements, actors, success criteria, constraints, and conflicts.",
        )
    else:
        completed.append("Candidate requirements have been extracted")

    clarification = read_text(feature_dir / "clarification-log.md")
    blocking_count = count_status_rows(clarification, "Blocking")
    open_count = count_status_rows(clarification, "Open")
    if blocking_count or open_count:
        blocking.append(f"clarification-log.md has {blocking_count} Blocking and {open_count} Open item(s)")
        mark_blocker(
            "Step 2 - Clarification Review",
            "Ask PO/TPM to resolve blocking and open clarification items.",
        )
    else:
        completed.append("No blocking or open clarification rows detected")

    readiness = read_text(feature_dir / "supporting-artifacts" / "readiness-checks.md")
    gaps = readiness_gaps(readiness)
    if gaps:
        blocking.extend(gaps)
        mark_blocker(
            "Step 2 - Dynamic Readiness Checks",
            "Complete required supporting artifacts or record valid N/A rationales.",
        )
    elif "TBD" in readiness:
        blocking.append("readiness-checks.md still contains TBD placeholders")
        mark_blocker(
            "Step 2 - Dynamic Readiness Checks",
            "Classify feature traits and supporting artifact requirements.",
        )
    else:
        completed.append("Dynamic readiness checks are complete")

    product = read_text(feature_dir / "product-spec.md")
    product_status = extract_field(product, "Status", "Draft")
    if product_status != "Accepted":
        blocking.append(f"product-spec.md status is {product_status}, not Accepted")
        mark_blocker(
            "Step 2 - Product Spec Review",
            "Refine product-spec.md and obtain PO/TPM acceptance evidence.",
        )
    elif "TBD" in product:
        risks.append("product-spec.md is Accepted but still contains TBD placeholders")
        review_step = "Step 2 - Product Spec Review"
        if primary_step is None:
            next_action = "Remove TBD placeholders or explicitly justify them before handoff."
    else:
        completed.append("product-spec.md is Accepted")

    accepted_inputs = accepted_speckit_inputs(feature_dir)
    if not accepted_inputs:
        blocking.append("No accepted speckit-input.md package found")
        mark_blocker(
            "Step 2 - Spec Kit Input Split",
            "Create one or more single-feature Spec Kit input packages and mark accepted packages.",
        )
    else:
        completed.append(f"{len(accepted_inputs)} accepted Spec Kit input package(s)")

    handoff = read_text(feature_dir / "handoff-checklist.md")
    handoff_status = extract_field(handoff, "Status", "Draft")
    unchecked = unchecked_checkboxes(handoff)
    if handoff_status != "Ready":
        blocking.append(f"handoff-checklist.md status is {handoff_status}, not Ready")
        mark_blocker(
            "Step 2 - Handoff Checklist",
            "Complete handoff-checklist.md after product spec and accepted inputs are ready.",
        )
    elif unchecked:
        blocking.append(f"handoff-checklist.md is Ready but has {len(unchecked)} unchecked item(s)")
        mark_blocker(
            "Step 2 - Handoff Checklist",
            "Resolve remaining handoff checklist items before handoff.",
        )
    else:
        completed.append("handoff-checklist.md is Ready")

    if not blocking and product_status == "Accepted" and accepted_inputs and handoff_status == "Ready":
        current_step = "Ready for Step 3 - speckit-specify"
        current_status = "Ready"
        next_action = "Run speckit-specify once per accepted speckit-input.md package."
    else:
        current_step = primary_step or review_step or "Step 2 - Requirement Readiness Review"
        current_status = "Blocked" if blocking else "In Review"

    return print_feature_report(current_step, current_status, completed, blocking, risks, next_action)


def print_feature_report(
    current_step: str,
    current_status: str,
    completed: list[str],
    blocking: list[str],
    risks: list[str],
    next_action: str,
) -> int:
    print(f"Current Step: {current_step}")
    print(f"Current Status: {current_status}")
    print_list("Completed", completed)
    print_list("Blocking", blocking)
    print_list("Non-blocking Risks", risks)
    print(f"Recommended Next Step: {next_action}")
    return 1 if current_status == "Blocked" else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("feature_slug", nargs="?", help="optional feature slug under docs/spec-intake")
    parser.add_argument("--repo-root", default=Path(__file__).resolve().parents[4], type=Path)
    args = parser.parse_args()

    root = args.repo_root.resolve()
    intake_root = root / "docs" / "spec-intake"

    if not args.feature_slug:
        return report_board(intake_root)

    try:
        slug = validate_slug(args.feature_slug)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return status_for_feature(intake_root, slug)


if __name__ == "__main__":
    raise SystemExit(main())
