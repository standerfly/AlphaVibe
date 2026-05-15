#!/usr/bin/env python3
"""Initialize an ADR-0027 pre-spec intake workspace."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import re
import subprocess
import sys


SKILL_DIR = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = SKILL_DIR / "assets" / "templates"
BASE_BRANCH = "develop"

DEFAULTS = {
    "FEATURE_TITLE": "TBD",
    "STATUS": "Draft",
    "PO": "TBD",
    "TPM": "TBD",
    "NOTES": "Initialized",
    "SPEC_FEATURE_SLUG": "TBD",
    "SPEC_FEATURE_TITLE": "TBD",
    "HANDOFF_ORDER": "TBD",
}

RAW_PLACEHOLDER_FILES = {".gitkeep"}

FILE_TEMPLATES = {
    "intake-index.md": "intake-index.md",
    "extracted-requirements.md": "extracted-requirements.md",
    "clarification-log.md": "clarification-log.md",
    "scope-decision.md": "scope-decision.md",
    "product-spec.md": "product-spec.md",
    "supporting-artifacts/readiness-checks.md": "readiness-checks.md",
    "spec-kit-inputs/index.md": "spec-kit-inputs-index.md",
    "handoff-checklist.md": "handoff-checklist.md",
}


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def git_current_branch(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True, cwd=repo_root,
    )
    if result.returncode != 0:
        fail("Unable to determine current git branch. Is this a git repository?")
    return result.stdout.strip()


def git_branch_exists(repo_root: Path, branch_name: str) -> bool:
    result = subprocess.run(
        ["git", "branch", "--list", branch_name],
        capture_output=True, text=True, cwd=repo_root,
    )
    return bool(result.stdout.strip())


def git_check_remote_sync(repo_root: Path) -> None:
    fetch = subprocess.run(
        ["git", "fetch", "origin", BASE_BRANCH],
        capture_output=True, text=True, cwd=repo_root,
    )
    if fetch.returncode != 0:
        print(f"Warning: Could not reach origin. Skipping remote sync check. ({fetch.stderr.strip()})")
        return

    local = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True, text=True, cwd=repo_root,
    )
    remote = subprocess.run(
        ["git", "rev-parse", f"origin/{BASE_BRANCH}"],
        capture_output=True, text=True, cwd=repo_root,
    )
    if local.returncode == 0 and remote.returncode == 0:
        if local.stdout.strip() != remote.stdout.strip():
            fail(
                f"Local '{BASE_BRANCH}' is not in sync with 'origin/{BASE_BRANCH}'. "
                f"Run 'git pull' on {BASE_BRANCH} before initializing."
            )


def git_create_branch(repo_root: Path, branch_name: str) -> None:
    result = subprocess.run(
        ["git", "checkout", "-b", branch_name],
        capture_output=True, text=True, cwd=repo_root,
    )
    if result.returncode != 0:
        fail(f"Failed to create branch '{branch_name}': {result.stderr.strip()}")
    print(f"Created and switched to branch: {branch_name}")


def setup_branch(repo_root: Path, slug: str) -> None:
    function_branch = f"function/{slug}"
    current = git_current_branch(repo_root)

    if current == function_branch:
        print(f"Already on branch: {function_branch}")
        return

    if current != BASE_BRANCH:
        fail(
            f"pre-spec workspaces must be initialized from '{BASE_BRANCH}'. "
            f"Current branch: '{current}'. "
            f"Switch to '{BASE_BRANCH}' first, or use --no-branch to skip branch creation."
        )

    if git_branch_exists(repo_root, function_branch):
        fail(
            f"Branch '{function_branch}' already exists. "
            f"Switch to it manually or use --no-branch to skip branch creation."
        )

    git_check_remote_sync(repo_root)
    git_create_branch(repo_root, function_branch)


def validate_slug(slug: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", slug):
        fail("feature slug must use letters, digits, dot, underscore, or hyphen")
    if ".." in slug or "/" in slug or "\\" in slug:
        fail("feature slug must not contain path traversal or path separators")
    return slug


def render_template(name: str, values: dict[str, str]) -> str:
    path = TEMPLATE_DIR / name
    if not path.exists():
        fail(f"missing template: {path}")
    text = path.read_text(encoding="utf-8")
    merged = dict(DEFAULTS)
    merged.update(values)
    for key, value in merged.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def write_if_missing(path: Path, content: str, created: list[Path], skipped: list[Path]) -> None:
    if path.exists():
        skipped.append(path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    created.append(path)


def has_raw_sources(feature_dir: Path) -> bool:
    raw_dir = feature_dir / "raw"
    if not raw_dir.exists():
        return False
    return any(
        path.is_file() and path.name not in RAW_PLACEHOLDER_FILES
        for path in raw_dir.rglob("*")
    )


def has_any_artifacts(feature_dir: Path) -> bool:
    return any((feature_dir / relative).exists() for relative in FILE_TEMPLATES)


def split_row(row: str) -> list[str]:
    return [cell.strip() for cell in row.strip().strip("|").split("|")]


def build_index_row(values: dict[str, str]) -> list[str]:
    slug = values["FEATURE_SLUG"]
    return [
        slug,
        values["FEATURE_TITLE"],
        values["STATUS"],
        values["PO"],
        values["TPM"],
        values.get("PRODUCT_SPEC_LINK", f"[product-spec.md]({slug}/product-spec.md)"),
        values.get("HANDOFF_CHECKLIST_LINK", f"[handoff-checklist.md]({slug}/handoff-checklist.md)"),
        values["DATE"],
        values["NOTES"],
    ]


def update_global_index(index_path: Path, values: dict[str, str]) -> None:
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
    rows: dict[str, list[str]] = {}
    if index_path.exists():
        for line in index_path.read_text(encoding="utf-8").splitlines():
            if not line.startswith("|") or "---" in line or "Feature Slug" in line:
                continue
            cells = split_row(line)
            if len(cells) == len(header):
                rows[cells[0]] = cells
    row = build_index_row(values)
    rows[row[0]] = row

    lines = [
        "# Spec Intake Index",
        "",
        "| " + " | ".join(header) + " |",
        "|--------------|-------|--------|----|-----|--------------|-------------------|--------------|-------|",
    ]
    for slug in sorted(rows):
        lines.append("| " + " | ".join(rows[slug]) + " |")
    lines.append("")
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("feature_slug", help="feature slug under docs/spec-intake")
    parser.add_argument("--repo-root", default=Path(__file__).resolve().parents[4], type=Path)
    parser.add_argument("--title", default=None, help="human-readable feature title")
    parser.add_argument("--po", default="TBD", help="product owner")
    parser.add_argument("--tpm", default="TBD", help="technical product manager")
    parser.add_argument("--status", default="Draft", help="global registry status")
    parser.add_argument("--notes", default=None, help="global registry note")
    parser.add_argument("--no-branch", action="store_true", help="skip branch creation and stay on current branch")
    parser.add_argument(
        "--with-artifacts",
        "--full",
        dest="with_artifacts",
        action="store_true",
        help="create the full pre-spec artifact skeleton even when raw/ has no source material",
    )
    args = parser.parse_args()

    root = args.repo_root.resolve()
    slug = validate_slug(args.feature_slug)

    if not args.no_branch:
        setup_branch(root, slug)
    title = args.title or slug.replace("-", " ").replace("_", " ").title()
    intake_root = root / "docs" / "spec-intake"
    feature_dir = intake_root / slug
    created: list[Path] = []
    skipped: list[Path] = []

    raw_dir = feature_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    if not has_raw_sources(feature_dir):
        write_if_missing(raw_dir / ".gitkeep", "", created, skipped)

    create_artifacts = args.with_artifacts or has_raw_sources(feature_dir) or has_any_artifacts(feature_dir)
    notes = args.notes
    if notes is None:
        notes = "Initialized" if create_artifacts else "Initialized; waiting for raw source material"

    values = {
        "FEATURE_SLUG": slug,
        "FEATURE_TITLE": title,
        "PO": args.po,
        "TPM": args.tpm,
        "STATUS": args.status,
        "NOTES": notes,
        "DATE": date.today().isoformat(),
    }
    if not create_artifacts:
        values["PRODUCT_SPEC_LINK"] = "Pending raw intake"
        values["HANDOFF_CHECKLIST_LINK"] = "Pending raw intake"

    update_global_index(intake_root / "index.md", values)

    if create_artifacts:
        for directory in [
            feature_dir / "supporting-artifacts",
            feature_dir / "spec-kit-inputs",
        ]:
            directory.mkdir(parents=True, exist_ok=True)

        for relative, template in FILE_TEMPLATES.items():
            write_if_missing(feature_dir / relative, render_template(template, values), created, skipped)

    print(f"Initialized pre-spec workspace: {feature_dir.relative_to(root)}")
    print(f"Updated global index: {(intake_root / 'index.md').relative_to(root)}")
    if create_artifacts:
        print("Artifact skeleton: ready")
    else:
        print("Artifact skeleton: deferred until raw source material is added")
        print("Next step: add raw source files under raw/, then rerun prespec_init.py.")
    if created:
        print("Created:")
        for path in created:
            print(f"- {path.relative_to(root)}")
    if skipped:
        print("Skipped existing:")
        for path in skipped:
            print(f"- {path.relative_to(root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
