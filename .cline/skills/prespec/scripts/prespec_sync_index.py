#!/usr/bin/env python3
"""Synchronize docs/spec-intake/index.md from feature workspaces."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import re
import sys

RAW_PLACEHOLDER_FILES = {".gitkeep"}
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


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def validate_slug(slug: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", slug):
        fail("feature slug must use letters, digits, dot, underscore, or hyphen")
    if ".." in slug or "/" in slug or "\\" in slug:
        fail("feature slug must not contain path traversal or path separators")
    return slug


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def raw_files(feature_dir: Path) -> list[Path]:
    raw_dir = feature_dir / "raw"
    if not raw_dir.exists():
        return []
    return sorted(
        path
        for path in raw_dir.rglob("*")
        if path.is_file() and path.name not in RAW_PLACEHOLDER_FILES
    )


def has_full_artifact_skeleton(feature_dir: Path) -> bool:
    return all((feature_dir / relative).exists() for relative in REQUIRED_FILES)


def extract_field(text: str, field: str, default: str = "TBD") -> str:
    match = re.search(rf"^\*\*{re.escape(field)}:\*\*\s*(.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else default


def extract_title(product_spec: str, slug: str) -> str:
    match = re.search(r"^# Product Spec:\s*(.+)$", product_spec, re.MULTILINE)
    if match:
        return match.group(1).strip()
    return slug.replace("-", " ").replace("_", " ").title()


def has_unchecked_checkbox(text: str) -> bool:
    return any(line.strip().startswith("- [ ]") for line in text.splitlines())


def derive_status(product_status: str, checklist_status: str, handoff: str) -> str:
    if checklist_status == "Ready":
        if product_status != "Accepted" or has_unchecked_checkbox(handoff):
            return "Blocked"
        return "Ready"
    if checklist_status == "Blocked":
        return "Blocked"
    if product_status in {"Accepted", "In Review", "Draft"}:
        return product_status
    return "Draft"


def derive_note(feature_dir: Path, status: str, product_status: str, checklist_status: str) -> str:
    if not raw_files(feature_dir) and not has_full_artifact_skeleton(feature_dir):
        return "Waiting for raw source material"
    if raw_files(feature_dir) and not has_full_artifact_skeleton(feature_dir):
        return "Raw source present; run prespec_init.py to create artifact skeleton"
    checklist = read_text(feature_dir / "handoff-checklist.md")
    unchecked = [line.strip() for line in checklist.splitlines() if line.strip().startswith("- [ ]")]
    if status == "Ready":
        return "Ready for Spec Kit handoff"
    if checklist_status == "Ready" and product_status != "Accepted":
        return "Blocked: checklist Ready but product spec is not Accepted"
    if checklist_status == "Ready" and unchecked:
        return "Blocked: checklist Ready but unchecked items remain"
    if unchecked:
        return unchecked[0].replace("- [ ]", "Missing:", 1).strip()
    return "Synced"


def existing_value(existing_row: list[str] | None, index: int, default: str) -> str:
    if existing_row and len(existing_row) > index and existing_row[index]:
        return existing_row[index]
    return default


def feature_row(feature_dir: Path, existing_row: list[str] | None = None) -> list[str]:
    slug = feature_dir.name
    minimal_workspace = not raw_files(feature_dir) and not has_full_artifact_skeleton(feature_dir)
    product_spec = read_text(feature_dir / "product-spec.md")
    handoff = read_text(feature_dir / "handoff-checklist.md")
    product_status = extract_field(product_spec, "Status", "Draft")
    checklist_status = extract_field(handoff, "Status", "Draft")
    status = derive_status(product_status, checklist_status, handoff)
    title = extract_title(product_spec, slug)
    po = extract_field(product_spec, "Product Owner", "TBD")
    tpm = extract_field(product_spec, "TPM", "TBD")
    if minimal_workspace:
        title = existing_value(existing_row, 1, title)
        po = existing_value(existing_row, 3, po)
        tpm = existing_value(existing_row, 4, tpm)
    return [
        slug,
        title,
        status,
        po,
        tpm,
        "Pending raw intake" if minimal_workspace else f"[product-spec.md]({slug}/product-spec.md)",
        "Pending raw intake" if minimal_workspace else f"[handoff-checklist.md]({slug}/handoff-checklist.md)",
        date.today().isoformat(),
        derive_note(feature_dir, status, product_status, checklist_status),
    ]


def write_index(intake_root: Path, rows: list[list[str]]) -> None:
    header = [
        "Feature Slug",
        "Title",
        "Status",
        "PO",
        "TPM",
        "Product Spec",
        "Handoff Checklist",
        "Last Updated",
        "Notes",
    ]
    lines = [
        "# Spec Intake Index",
        "",
        "| " + " | ".join(header) + " |",
        "|--------------|-------|--------|----|-----|--------------|-------------------|--------------|-------|",
    ]
    for row in sorted(rows, key=lambda item: item[0]):
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    intake_root.mkdir(parents=True, exist_ok=True)
    with (intake_root / "index.md").open("w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("feature_slug", nargs="?", help="optional feature slug to sync")
    parser.add_argument("--repo-root", default=Path(__file__).resolve().parents[4], type=Path)
    args = parser.parse_args()

    root = args.repo_root.resolve()
    intake_root = root / "docs" / "spec-intake"

    if not intake_root.exists():
        fail("docs/spec-intake does not exist")

    if args.feature_slug:
        slug = validate_slug(args.feature_slug)
        feature_dirs = [intake_root / slug]
        if not feature_dirs[0].is_dir():
            fail(f"feature workspace does not exist: docs/spec-intake/{slug}")
    else:
        feature_dirs = sorted(path for path in intake_root.iterdir() if path.is_dir())

    existing = parse_existing_rows(intake_root / "index.md") if (intake_root / "index.md").exists() else {}
    rows = [feature_row(feature_dir, existing.get(feature_dir.name)) for feature_dir in feature_dirs]
    if args.feature_slug:
        existing[args.feature_slug] = rows[0]
        rows = list(existing.values())
    write_index(intake_root, rows)
    print(f"Synced global intake index: {(intake_root / 'index.md').relative_to(root)}")
    return 0


def parse_existing_rows(index_path: Path) -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    for line in read_text(index_path).splitlines():
        if not line.startswith("|") or "---" in line or "Feature Slug" in line:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 9:
            rows[cells[0]] = cells
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
