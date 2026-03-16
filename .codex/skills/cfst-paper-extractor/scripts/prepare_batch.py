#!/usr/bin/env python3
"""Prepare a CFST batch workspace from processed paper folders."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from reorganize_parsed_with_tables import write_json  # noqa: E402

PAPER_ID_PATTERN = re.compile(r"\[(A\d+-\d+)\]")


def discover_processed_paper_dirs(processed_root: Path, include_regex: str | None) -> dict[str, Path]:
    pattern = re.compile(include_regex) if include_regex else None
    paper_dirs: dict[str, Path] = {}
    for item in sorted(processed_root.iterdir()):
        if not item.is_dir():
            continue
        if pattern and not pattern.search(item.name):
            continue
        match = PAPER_ID_PATTERN.search(item.name)
        if not match:
            continue
        paper_id = match.group(1)
        paper_dirs[paper_id] = item
    return paper_dirs


def git_repo_status(cwd: Path) -> dict[str, Any]:
    proc = subprocess.run(
        ["git", "-C", str(cwd), "rev-parse", "--is-inside-work-tree"],
        check=False,
        text=True,
        capture_output=True,
    )
    return {
        "is_git_repo": proc.returncode == 0 and proc.stdout.strip() == "true",
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
    }


def infer_paper_title_hint(processed_dir: Path) -> str:
    text = processed_dir.name
    text = re.sub(r"^\[[^\]]+\]\s*", "", text)
    return text.strip()


def build_folder_metadata(processed_dirs: dict[str, Path], paper_id: str) -> dict[str, Any]:
    processed_dir = processed_dirs.get(paper_id)
    return {
        "paper_id": paper_id,
        "citation_tag": f"[{paper_id}]",
        "paper_title_hint": infer_paper_title_hint(processed_dir) if processed_dir else "",
        "expected_specimen_count": None,
    }


def count_files(root: Path, *, skip_names: set[str] | None = None) -> int:
    if not root.exists() or not root.is_dir():
        return 0
    skip_names = skip_names or set()
    return sum(1 for path in root.rglob("*") if path.is_file() and path.name not in skip_names)


def inspect_processed_layout(paper_dir: Path) -> dict[str, Any]:
    markdown_files = sorted(path.name for path in paper_dir.iterdir() if path.is_file() and path.suffix.lower() == ".md")
    parse_json_files = sorted(
        path.name for path in paper_dir.iterdir()
        if path.is_file() and path.suffix.lower() == ".json" and path.stem != "paper_manifest"
    )
    images_dir = paper_dir / "images"
    tables_dir = paper_dir / "tables"
    tables_manifest = tables_dir / "manifest.json"

    issues: list[str] = []
    if len(markdown_files) != 1:
        issues.append("expected_exactly_one_markdown_file")
    if len(parse_json_files) != 1:
        issues.append("expected_exactly_one_parse_json_file")
    if not images_dir.is_dir():
        issues.append("missing_images_dir")
    if not tables_dir.is_dir():
        issues.append("missing_tables_dir")
    if not tables_manifest.is_file():
        issues.append("missing_tables_manifest")

    return {
        "ready": not issues,
        "markdown_file": markdown_files[0] if len(markdown_files) == 1 else None,
        "parse_json_file": parse_json_files[0] if len(parse_json_files) == 1 else None,
        "markdown_files": markdown_files,
        "parse_json_files": parse_json_files,
        "images_dir": str(images_dir) if images_dir.is_dir() else None,
        "tables_dir": str(tables_dir) if tables_dir.is_dir() else None,
        "tables_manifest": str(tables_manifest) if tables_manifest.is_file() else None,
        "images_count": count_files(images_dir),
        "table_image_count": count_files(tables_dir, skip_names={"manifest.json"}),
        "issues": issues,
    }


def paper_dir_relpath(worktree_root: Path, paper_dir: Path) -> str | None:
    try:
        return paper_dir.resolve().relative_to(worktree_root).as_posix()
    except ValueError:
        return None


def build_worker_job(
    output_root: Path,
    paper_id: str,
    paper_dir_relpath_value: str | None,
    expected_specimen_count: int | None,
    status: str,
) -> dict[str, Any]:
    tmp_json = output_root / "tmp" / paper_id / f"{paper_id}.json"
    final_json = output_root / "output" / f"{paper_id}.json"
    return {
        "paper_id": paper_id,
        "paper_dir_relpath": paper_dir_relpath_value,
        "worker_output_json_path": str(tmp_json),
        "final_output_json_path": str(final_json),
        "expected_specimen_count": expected_specimen_count,
        "status": status,
    }


def selected_paper_ids(processed_dirs: dict[str, Path], explicit_ids: list[str] | None) -> list[str]:
    ids = explicit_ids or sorted(processed_dirs.keys())
    return sorted(set(ids), key=lambda value: tuple(int(x) for x in re.findall(r"\d+", value)) or (10**9,))


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare CFST batch workspace from processed paper folders.")
    parser.add_argument(
        "--processed-root",
        type=Path,
        required=True,
        help="Root containing processed paper folders (markdown + parse json + images + tables).",
    )
    parser.add_argument(
        "--worktree-root",
        type=Path,
        default=Path("."),
        help="Repository/worktree root used to compute worker paper_dir_relpath values.",
    )
    parser.add_argument("--output-root", type=Path, required=True, help="Batch output root.")
    parser.add_argument(
        "--include-regex",
        default=r"^\[A\d+-\d+\]",
        help="Regex for processed paper folder discovery.",
    )
    parser.add_argument(
        "--paper-ids",
        nargs="*",
        default=None,
        help="Optional explicit list like A1-1 A1-2.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Do not write files.")
    args = parser.parse_args()

    processed_root = args.processed_root.resolve()
    if not processed_root.exists():
        print(f"[FAIL] Processed root not found: {processed_root}")
        return 1
    if not processed_root.is_dir():
        print(f"[FAIL] Processed root is not a directory: {processed_root}")
        return 1

    worktree_root = args.worktree_root.resolve()
    if not worktree_root.exists() or not worktree_root.is_dir():
        print(f"[FAIL] Worktree root not found or not a directory: {worktree_root}")
        return 1

    output_root = args.output_root.resolve()
    manifests_dir = output_root / "manifests"
    logs_dir = output_root / "logs"
    tmp_dir = output_root / "tmp"
    final_output_dir = output_root / "output"

    processed_dirs = discover_processed_paper_dirs(processed_root, args.include_regex)
    selected_ids = selected_paper_ids(processed_dirs, args.paper_ids)

    batch_entries: list[dict[str, Any]] = []
    worker_jobs: list[dict[str, Any]] = []
    state_entries: list[dict[str, Any]] = []

    for paper_id in selected_ids:
        folder_metadata = build_folder_metadata(processed_dirs, paper_id)
        processed_dir = processed_dirs.get(paper_id)
        layout = inspect_processed_layout(processed_dir) if processed_dir else None
        dir_relpath = paper_dir_relpath(worktree_root, processed_dir) if processed_dir else None

        status = "missing_processed_data"
        if processed_dir and layout:
            if dir_relpath is None:
                status = "outside_worktree"
            elif layout["ready"]:
                status = "prepared"
            else:
                status = "invalid_processed_layout"

        batch_entry = {
            "paper_id": paper_id,
            "citation_tag": folder_metadata["citation_tag"],
            "paper_title_hint": folder_metadata["paper_title_hint"],
            "expected_specimen_count": folder_metadata["expected_specimen_count"],
            "processed_dir": str(processed_dir) if processed_dir else None,
            "paper_dir_relpath": dir_relpath,
            "status": status,
            "layout": layout,
        }
        batch_entries.append(batch_entry)
        worker_jobs.append(
            build_worker_job(
                output_root=output_root,
                paper_id=paper_id,
                paper_dir_relpath_value=dir_relpath if status == "prepared" else None,
                expected_specimen_count=folder_metadata["expected_specimen_count"],
                status=status,
            )
        )
        state_entries.append(
            {
                "paper_id": paper_id,
                "status": status,
                "retry_count": 0,
                "validated": False,
                "published": False,
                "last_error": None,
            }
        )

    batch_manifest = {
        "schema_version": "cfst-batch-manifest-v3",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_layout": "processed-paper-dir",
        "processed_root": str(processed_root),
        "worktree_root": str(worktree_root),
        "output_root": str(output_root),
        "git_status": git_repo_status(worktree_root),
        "paper_count": len(batch_entries),
        "papers": batch_entries,
    }

    batch_state = {
        "schema_version": "cfst-batch-state-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "paper_count": len(state_entries),
        "papers": state_entries,
    }

    if not args.dry_run:
        for directory in (manifests_dir, logs_dir, tmp_dir, final_output_dir):
            directory.mkdir(parents=True, exist_ok=True)
        write_json(manifests_dir / "batch_manifest.json", batch_manifest)
        write_json(manifests_dir / "worker_jobs.json", worker_jobs)
        write_json(manifests_dir / "batch_state.json", batch_state)

    prepared_count = sum(1 for item in batch_entries if item["status"] == "prepared")
    invalid_count = sum(1 for item in batch_entries if item["status"] == "invalid_processed_layout")
    print(f"[OK] Indexed {len(batch_entries)} papers from processed root.")
    print(f"[INFO] Prepared={prepared_count} InvalidLayout={invalid_count}")
    print(f"[INFO] Git repo present: {batch_manifest['git_status']['is_git_repo']}")
    print(f"[INFO] Output root: {output_root}")
    if not args.dry_run:
        print(f"[OK] Batch manifest: {manifests_dir / 'batch_manifest.json'}")
        print(f"[OK] Worker jobs: {manifests_dir / 'worker_jobs.json'}")
        print(f"[OK] Batch state: {manifests_dir / 'batch_state.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
