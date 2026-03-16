#!/usr/bin/env python3
"""Convert a raw MinerU batch directory into the processed/ layout expected by prepare_batch.py.

This is a convenience wrapper around reorganize_parsed_with_tables.py that:
- Uses bracket-prefixed folder names ([A1-1]) compatible with prepare_batch.py
- Injects table image references into the output markdown by default
- Validates the output layout after conversion
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from prepare_batch import inspect_processed_layout  # noqa: E402
from reorganize_parsed_with_tables import (  # noqa: E402
    DEFAULT_INCLUDE_PATTERN,
    extract_paper_id,
    infer_paper_id,
    reorganize_one_paper,
    write_json,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert raw MinerU batch directory into processed/ layout."
    )
    parser.add_argument(
        "--batch-dir",
        type=Path,
        required=True,
        help="Raw MinerU batch directory (e.g., batch1/).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("processed"),
        help="Output directory for processed paper folders. Default: processed/",
    )
    parser.add_argument(
        "--id-regex",
        default=r"\[(?P<id>A\d+-\d+)\]",
        help="Regex to extract paper id from folder names.",
    )
    parser.add_argument(
        "--include-regex",
        default=DEFAULT_INCLUDE_PATTERN,
        help="Only process folders whose names match this regex.",
    )
    parser.add_argument(
        "--exclude-regex",
        default=None,
        help="Skip folders whose names match this regex.",
    )
    parser.add_argument(
        "--no-inject-table-images",
        action="store_true",
        help="Do not inject table image references into markdown.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview actions without writing files.",
    )
    return parser.parse_args()


def main() -> int:
    import re

    args = parse_args()

    batch_dir: Path = args.batch_dir
    if not batch_dir.exists() or not batch_dir.is_dir():
        print(f"[FAIL] Batch directory not found: {batch_dir}")
        return 1

    output_dir: Path = args.output_dir
    inject = not args.no_inject_table_images

    include_pattern = re.compile(args.include_regex) if args.include_regex else None
    exclude_pattern = re.compile(args.exclude_regex) if args.exclude_regex else None

    print(f"Batch dir:  {batch_dir}")
    print(f"Output dir: {output_dir}")
    print(f"Inject table images: {inject}")
    if args.dry_run:
        print("[DRY RUN]")
    print()

    processed_papers: list[dict] = []
    skipped = 0

    for item in sorted(batch_dir.iterdir()):
        if not item.is_dir():
            continue
        if include_pattern and not include_pattern.search(item.name):
            continue
        if exclude_pattern and exclude_pattern.search(item.name):
            continue

        paper_id = extract_paper_id(item.name, args.id_regex)
        if not paper_id:
            paper_id = infer_paper_id(item.name)

        paper_token = f"[{paper_id}]"

        stats = reorganize_one_paper(
            src_paper_dir=item,
            dst_root=output_dir,
            paper_token=paper_token,
            dry_run=args.dry_run,
            copy_legacy_json=False,
            inject_table_images=inject,
        )
        if stats is None:
            skipped += 1
            continue

        processed_papers.append({
            "paper_id": paper_id,
            "paper_token": paper_token,
            "tables_copied": stats["tables_copied"],
            "tables_detected": stats["tables_detected"],
            "tables_injected": stats.get("tables_injected", 0),
            "images_all": stats["images_all"],
        })
        inject_info = f", {stats.get('tables_injected', 0)} refs injected" if inject else ""
        print(
            f"  [OK] {paper_token}: "
            f"{stats['images_all']} images, "
            f"{stats['tables_copied']}/{stats['tables_detected']} tables"
            f"{inject_info}"
        )

    # Validate output layout
    print(f"\n=== Conversion Summary ===")
    print(f"Papers processed: {len(processed_papers)}")
    print(f"Papers skipped: {skipped}")

    if not args.dry_run and processed_papers:
        print(f"\n=== Layout Validation ===")
        ready_count = 0
        issue_count = 0
        for paper in processed_papers:
            paper_dir = output_dir / paper["paper_token"]
            layout = inspect_processed_layout(paper_dir)
            if layout["ready"]:
                ready_count += 1
            else:
                issue_count += 1
                print(f"  [WARN] {paper['paper_token']}: {layout['issues']}")
        print(f"Ready: {ready_count}, Issues: {issue_count}")

    if not args.dry_run and processed_papers:
        summary = {
            "batch_dir": str(batch_dir),
            "output_dir": str(output_dir),
            "inject_table_images": inject,
            "papers": processed_papers,
        }
        summary_path = output_dir / "normalize_summary.json"
        write_json(summary_path, summary)
        print(f"\nSummary written to: {summary_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
