#!/usr/bin/env python3
"""Validate mechanical ADR-0027 pre-spec workspace consistency."""

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

CORE_SPECKIT_INPUT_SECTIONS = [
    "Feature Summary",
    "Actors",
    "Problem And Goal",
    "In Scope",
    "Out Of Scope",
    "User Scenarios",
    "Functional Requirements",
    "Success Criteria",
    "Constraints And Assumptions",
    "Dependencies",
    "Supporting Artifact Coverage",
    "Source Decisions",
]

READINESS_TRAIT_SECTION_MAP = {
    "multi-role, multi-system, or multi-step workflow": ["Workflow And Call Ordering"],
    "async job, callback, event handling, or state transition": ["Order State And Idempotency"],
    "new or changed external/internal api behavior": [
        "API Contract Summary",
        "Non-Call And No-Change Constraints",
    ],
    "third-party or cross-system integration": ["Integration, Timeout, Retry, And Data Mapping"],
    "new or changed data lifecycle": ["Data Model And Compatibility"],
    "permission, role, or approval behavior": ["Permission And Approval Behavior"],
    "security, privacy, compliance, or audit concern": [
        "Error Handling Matrix",
        "Observability And Recovery",
    ],
    "import, export, or batch processing": ["Validation And Partial Failure Policy"],
    "high-risk, irreversible, payment, order, or control flow": [
        "Order State And Idempotency",
        "Error Handling Matrix",
    ],
    "operationally sensitive behavior": ["Observability And Recovery"],
}


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


def has_unchecked_checkbox(text: str) -> bool:
    return any(line.strip().startswith("- [ ]") for line in text.splitlines())


def section_has_unchecked_checkbox(text: str, section_title: str) -> bool:
    in_section = False
    section_heading = f"## {section_title}".lower()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_section = stripped.lower() == section_heading
            continue
        if in_section and stripped.startswith("- [ ]"):
            return True
    return False


def normalized_cell(value: str) -> str:
    return value.strip().lower()


def table_rows(text: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in text.splitlines():
        if not line.startswith("|") or "---" in line:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        rows.append(cells)
    return rows


def has_registry_entry(index_text: str, slug: str) -> bool:
    return any(row and row[0] == slug for row in table_rows(index_text))


def raw_files(feature_dir: Path) -> list[str]:
    raw_dir = feature_dir / "raw"
    if not raw_dir.exists():
        return []
    files = []
    for path in raw_dir.rglob("*"):
        if path.is_file() and path.name not in RAW_PLACEHOLDER_FILES:
            files.append(path.relative_to(feature_dir).as_posix())
    return sorted(files)


def has_any_artifacts(feature_dir: Path) -> bool:
    return any((feature_dir / relative).exists() for relative in REQUIRED_FILES)


def missing_sections(text: str, section_titles: list[str]) -> list[str]:
    headings = set()
    for line in text.splitlines():
        match = re.match(r"^##\s+(.+?)\s*$", line)
        if match:
            headings.add(match.group(1).strip().lower())
    return [title for title in section_titles if title.lower() not in headings]


def required_speckit_input_sections(readiness: str) -> list[str]:
    sections: list[str] = []
    seen: set[str] = set()

    def add(title: str) -> None:
        key = title.lower()
        if key not in seen:
            sections.append(title)
            seen.add(key)

    for title in CORE_SPECKIT_INPUT_SECTIONS:
        add(title)

    for cells in table_rows(readiness):
        if not cells or cells[0] == "Feature Trait" or len(cells) < 6:
            continue
        trait = normalized_cell(cells[0])
        detected = normalized_cell(cells[1])
        if detected not in {"yes", "required", "true"}:
            continue
        for title in READINESS_TRAIT_SECTION_MAP.get(trait, []):
            add(title)
    return sections


def validate_feature(intake_root: Path, slug: str) -> tuple[list[str], list[str]]:
    issues: list[str] = []
    warnings: list[str] = []
    feature_dir = intake_root / slug

    if not feature_dir.is_dir():
        return [f"Missing feature workspace: docs/spec-intake/{slug}"], warnings

    global_index = read_text(intake_root / "index.md")
    if not global_index:
        issues.append("Missing docs/spec-intake/index.md")
    elif not has_registry_entry(global_index, slug):
        issues.append("Global index does not list this feature workspace")
    if "raw/" in global_index:
        issues.append("Global index appears to contain raw source details")

    raw = raw_files(feature_dir)
    raw_dir = feature_dir / "raw"
    if not raw_dir.is_dir():
        issues.append("Missing raw source directory: raw/")
    if not raw and not has_any_artifacts(feature_dir):
        warnings.append("No raw source material found; pre-spec artifact skeleton is deferred")
        return issues, warnings

    for relative in REQUIRED_FILES:
        if not (feature_dir / relative).exists():
            issues.append(f"Missing required file: {relative}")

    intake_index = read_text(feature_dir / "intake-index.md")
    for raw_file in raw:
        if raw_file not in intake_index:
            issues.append(f"Raw source not listed in intake-index.md: {raw_file}")

    product_spec = read_text(feature_dir / "product-spec.md")
    product_status = extract_field(product_spec, "Status", "Draft")
    if product_status == "Accepted":
        for field in ["Product Owner", "TPM", "Accepted At", "Acceptance Evidence"]:
            value = extract_field(product_spec, field, "")
            if not value or value in {"TBD", "N/A", "[name]"}:
                issues.append(f"Accepted product-spec.md missing durable {field}")

    clarification_log = read_text(feature_dir / "clarification-log.md")
    if re.search(r"\|\s*Blocking\s*\|", clarification_log, re.IGNORECASE):
        issues.append("clarification-log.md has blocking clarification entries")

    readiness = read_text(feature_dir / "supporting-artifacts" / "readiness-checks.md")
    for line in readiness.splitlines():
        if not line.startswith("|") or "---" in line or "Feature Trait" in line:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) >= 6:
            detected, status, rationale = cells[1], cells[3], cells[5]
            detected_value = normalized_cell(detected)
            status_value = normalized_cell(status)
            rationale_value = normalized_cell(rationale)
            if detected_value in {"yes", "required", "true"} and status_value != "complete":
                issues.append(f"Required readiness check is incomplete: {cells[0]}")
            if status_value == "n/a" and rationale_value in {"", "tbd", "n/a"}:
                issues.append(f"N/A readiness check missing rationale: {cells[0]}")

    handoff = read_text(feature_dir / "handoff-checklist.md")
    handoff_status = extract_field(handoff, "Status", "Draft")
    if handoff_status == "Ready" and has_unchecked_checkbox(handoff):
        issues.append("handoff-checklist.md is Ready but has unchecked checklist items")
    if handoff_status == "Ready" and product_status != "Accepted":
        issues.append("handoff-checklist.md is Ready but product-spec.md is not Accepted")

    for speckit_input in (feature_dir / "spec-kit-inputs").glob("*/speckit-input.md"):
        text = read_text(speckit_input)
        input_status = extract_field(text, "Status", "Draft")
        missing = missing_sections(text, required_speckit_input_sections(readiness))
        if missing:
            message = (
                f"{speckit_input.relative_to(intake_root)} missing self-contained "
                f"section(s): {', '.join(missing)}"
            )
            if input_status == "Accepted":
                issues.append(message)
            else:
                warnings.append(message)
        if "TBD" in text:
            message = f"{speckit_input.relative_to(intake_root)} still contains TBD placeholders"
            if input_status == "Accepted":
                issues.append(message)
            else:
                warnings.append(message)
        if input_status == "Accepted":
            if product_status != "Accepted":
                issues.append(f"Accepted speckit input before product baseline acceptance: {speckit_input}")
            if handoff_status != "Ready":
                issues.append(f"Accepted speckit input before handoff checklist is Ready: {speckit_input}")
            if section_has_unchecked_checkbox(handoff, "Handoff Approval"):
                issues.append(f"Accepted speckit input before handoff approval is complete: {speckit_input}")

    if "TBD" in product_spec:
        warnings.append("product-spec.md still contains TBD placeholders")
    if "TBD" in readiness:
        warnings.append("readiness-checks.md still contains TBD placeholders")

    return issues, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("feature_slug", help="feature slug under docs/spec-intake")
    parser.add_argument("--repo-root", default=Path(__file__).resolve().parents[4], type=Path)
    args = parser.parse_args()

    try:
        slug = validate_slug(args.feature_slug)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    intake_root = args.repo_root.resolve() / "docs" / "spec-intake"
    issues, warnings = validate_feature(intake_root, slug)
    if warnings:
        print("Warnings:")
        for warning in warnings:
            print(f"- {warning}")
    if issues:
        print("Validation failed:")
        for issue in issues:
            print(f"- {issue}")
        return 1
    print(f"Pre-spec workspace is mechanically valid: docs/spec-intake/{slug}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
