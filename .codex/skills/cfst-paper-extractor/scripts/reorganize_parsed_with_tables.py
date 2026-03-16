#!/usr/bin/env python3
"""Normalize raw MinerU parsed papers into a processed-style layout with table manifests."""

from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

INVALID_FILENAME_CHARS = re.compile(r"[\\/:*?\"<>|]+")
WHITESPACE = re.compile(r"\s+")
DEFAULT_INCLUDE_PATTERN = r"^\[A\d+-\d+\]"


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def find_parse_dir(src_dir: Path) -> Path | None:
    """Find parse leaf directory, preferring hybrid_auto over auto."""
    hybrid_dirs = sorted(src_dir.rglob("hybrid_auto"))
    if hybrid_dirs:
        return hybrid_dirs[0]

    auto_dirs = sorted(src_dir.rglob("auto"))
    if auto_dirs:
        return auto_dirs[0]

    return None


def infer_paper_id(folder_name: str) -> str:
    bracket_match = re.search(r"\[([^\[\]]+)\]", folder_name)
    if bracket_match:
        return bracket_match.group(1).strip()

    if "__" in folder_name:
        head = folder_name.split("__", 1)[0].strip()
        if head:
            return head.strip("[] ")

    fallback = folder_name.strip().strip("[] ")
    return fallback or folder_name.strip()


def extract_paper_id(folder_name: str, id_regex: str | None) -> str | None:
    if not id_regex:
        return infer_paper_id(folder_name)

    try:
        match = re.search(id_regex, folder_name)
    except re.error:
        return None
    if not match:
        return None

    group_dict = match.groupdict()
    if "id" in group_dict and group_dict["id"]:
        return group_dict["id"].strip()
    if match.groups():
        return match.group(1).strip()
    return match.group(0).strip()


def caption_from_nodes(nodes: Any) -> str:
    if not isinstance(nodes, list):
        return ""

    parts: list[str] = []
    for node in nodes:
        if isinstance(node, dict):
            content = node.get("content")
            if isinstance(content, str):
                parts.append(content)
        elif isinstance(node, str):
            parts.append(node)
    return "".join(parts).strip()


def parse_legacy_table_item(item: dict[str, Any]) -> dict[str, Any] | None:
    if item.get("type") != "table":
        return None

    img_path = item.get("img_path")
    if not isinstance(img_path, str) or not img_path:
        return None

    table_caption = item.get("table_caption")
    caption = caption_from_nodes(table_caption) if isinstance(table_caption, list) else str(table_caption or "").strip()
    page_idx = item.get("page_idx")
    if not isinstance(page_idx, int):
        page_idx = None

    return {
        "img_path": img_path,
        "caption": caption,
        "page_idx": page_idx,
        "source": "legacy",
    }


def iter_v2_nodes(node: Any):
    if isinstance(node, list):
        for item in node:
            yield from iter_v2_nodes(item)
    elif isinstance(node, dict):
        yield node
        for value in node.values():
            yield from iter_v2_nodes(value)


def parse_v2_table_items(content_v2: Any) -> list[dict[str, Any]]:
    if not isinstance(content_v2, list):
        return []

    parsed: list[dict[str, Any]] = []
    for page_idx, page in enumerate(content_v2):
        for item in iter_v2_nodes(page):
            if not isinstance(item, dict) or item.get("type") != "table":
                continue

            content = item.get("content")
            if not isinstance(content, dict):
                continue

            image_source = content.get("image_source")
            if not isinstance(image_source, dict):
                continue

            img_path = image_source.get("path")
            if not isinstance(img_path, str) or not img_path:
                continue

            caption = caption_from_nodes(content.get("table_caption"))
            parsed.append(
                {
                    "img_path": img_path,
                    "caption": caption,
                    "page_idx": page_idx,
                    "source": "v2",
                }
            )

    return parsed


def collect_table_images(legacy_content: Any, v2_content: Any) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    seen_order: list[str] = []

    def upsert(record: dict[str, Any]) -> None:
        img_path = record["img_path"]
        caption = str(record.get("caption", "")).strip()
        page_idx = record.get("page_idx")
        source = record.get("source", "unknown")

        existing = merged.get(img_path)
        if existing is None:
            merged[img_path] = {
                "img_path": img_path,
                "caption": caption,
                "page_idx": page_idx if isinstance(page_idx, int) else None,
                "source": source,
            }
            seen_order.append(img_path)
            return

        if len(caption) > len(existing["caption"]):
            existing["caption"] = caption
            existing["source"] = source
        if existing["page_idx"] is None and isinstance(page_idx, int):
            existing["page_idx"] = page_idx

    if isinstance(legacy_content, list):
        for item in legacy_content:
            if not isinstance(item, dict):
                continue
            parsed = parse_legacy_table_item(item)
            if parsed:
                upsert(parsed)

    for parsed in parse_v2_table_items(v2_content):
        upsert(parsed)

    order_index = {img: idx for idx, img in enumerate(seen_order)}
    return sorted(
        merged.values(),
        key=lambda item: (
            item["page_idx"] if isinstance(item["page_idx"], int) else 10**9,
            order_index.get(item["img_path"], 10**9),
        ),
    )


def sanitize_table_title(title: str) -> str:
    cleaned = WHITESPACE.sub(" ", title).strip()
    cleaned = INVALID_FILENAME_CHARS.sub(" ", cleaned)
    cleaned = WHITESPACE.sub(" ", cleaned).strip(" .")
    if len(cleaned) > 120:
        cleaned = cleaned[:120].rstrip(" .")
    return cleaned


def unique_filename(base_name: str, suffix: str, used: set[str]) -> str:
    if not base_name:
        base_name = "table"
    candidate = f"{base_name}{suffix}"
    idx = 2
    while candidate in used:
        candidate = f"{base_name}_{idx}{suffix}"
        idx += 1
    used.add(candidate)
    return candidate


def copy_images_dir(src_images: Path, dst_images: Path, dry_run: bool) -> int:
    if not src_images.exists() or not src_images.is_dir():
        return 0

    image_count = sum(1 for p in src_images.rglob("*") if p.is_file())
    if dry_run:
        return image_count

    shutil.copytree(src_images, dst_images, dirs_exist_ok=True)
    return image_count


def resolve_table_image_path(parse_dir: Path, raw_img_path: str) -> Path | None:
    path = Path(raw_img_path)
    candidates: list[Path] = []
    if path.is_absolute():
        candidates.append(path)
    else:
        normalized = raw_img_path.strip()
        normalized = re.sub(r"^\./", "", normalized)
        normalized = re.sub(r"^\.\\", "", normalized)
        rel_path = Path(normalized)
        candidates.append(parse_dir / rel_path)
        candidates.append(parse_dir / "images" / rel_path.name)

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def build_table_manifest(
    parse_dir: Path,
    table_items: list[dict[str, Any]],
    dst_table_dir: Path,
    dry_run: bool,
) -> tuple[list[dict[str, Any]], int]:
    used_names: set[str] = set()
    manifest: list[dict[str, Any]] = []
    missing = 0

    if not dry_run:
        dst_table_dir.mkdir(parents=True, exist_ok=True)

    for idx, item in enumerate(table_items, start=1):
        img_path = str(item.get("img_path", "")).strip()
        caption = str(item.get("caption", "")).strip()
        page_idx = item.get("page_idx")

        record = {
            "index": idx,
            "raw_img_path": img_path,
            "caption": caption,
            "page_idx": page_idx,
            "source_kind": item.get("source", "unknown"),
            "source_exists": False,
            "source_path": None,
            "normalized_filename": None,
            "normalized_relpath": None,
        }

        if not img_path:
            missing += 1
            manifest.append(record)
            continue

        src = resolve_table_image_path(parse_dir, img_path)
        if src is None:
            missing += 1
            manifest.append(record)
            continue

        suffix = src.suffix or ".jpg"
        base_name = sanitize_table_title(caption) or f"table_{idx}"
        filename = unique_filename(base_name, suffix, used_names)
        dst = dst_table_dir / filename

        record["source_exists"] = True
        record["source_path"] = str(src)
        record["normalized_filename"] = filename
        record["normalized_relpath"] = f"tables/{filename}"

        if not dry_run:
            shutil.copy2(src, dst)
        manifest.append(record)

    return manifest, missing


def inject_table_image_refs(md_text: str, manifest: list[dict[str, Any]]) -> str:
    """Insert ![caption](tables/filename) before each <table> tag using sequential matching."""
    available = [
        entry for entry in manifest
        if entry.get("source_exists") and entry.get("normalized_relpath")
    ]
    if not available:
        return md_text

    table_tag = "<table>"
    parts: list[str] = []
    remaining = md_text
    match_idx = 0

    while True:
        pos = remaining.find(table_tag)
        if pos == -1:
            parts.append(remaining)
            break

        if match_idx < len(available):
            entry = available[match_idx]
            caption = entry.get("caption", "").strip()
            relpath = entry["normalized_relpath"]
            alt_text = caption or f"table_{match_idx + 1}"
            ref_line = f"![{alt_text}]({relpath})\n\n"
            parts.append(remaining[:pos])
            parts.append(ref_line)
            parts.append(remaining[pos : pos + len(table_tag)])
            match_idx += 1
        else:
            parts.append(remaining[: pos + len(table_tag)])

        remaining = remaining[pos + len(table_tag) :]

    return "".join(parts)


def reorganize_one_paper(
    src_paper_dir: Path,
    dst_root: Path,
    paper_token: str,
    dry_run: bool,
    copy_legacy_json: bool,
    inject_table_images: bool = False,
) -> dict[str, Any] | None:
    parse_dir = find_parse_dir(src_paper_dir)
    if parse_dir is None:
        print(f"  [SKIP] parse leaf not found (expect auto/hybrid_auto): {src_paper_dir.name}")
        return None

    md_files = sorted(parse_dir.glob("*.md"))
    legacy_json_files = sorted(parse_dir.glob("*_content_list.json"))
    v2_json_files = sorted(parse_dir.glob("*_content_list_v2.json"))
    images_dir = parse_dir / "images"

    if not md_files:
        print(f"  [SKIP] markdown not found: {src_paper_dir.name}")
        return None
    if not v2_json_files:
        print(f"  [SKIP] *_content_list_v2.json not found: {src_paper_dir.name}")
        return None

    legacy_content = read_json(legacy_json_files[0]) if legacy_json_files else None
    v2_content = read_json(v2_json_files[0])
    table_items = collect_table_images(legacy_content, v2_content)

    paper_dst = dst_root / paper_token
    dst_md = paper_dst / f"{paper_token}.md"
    dst_v2 = paper_dst / f"{paper_token}.json"
    dst_legacy = paper_dst / f"{paper_token}_content_list.json"
    dst_images = paper_dst / "images"
    dst_table = paper_dst / "tables"

    stats = {
        "paper_token": paper_token,
        "source_paper_dir": str(src_paper_dir),
        "source_parse_dir": str(parse_dir),
        "normalized_paper_dir": str(paper_dst),
        "images_all": 0,
        "tables_detected": len(table_items),
        "tables_copied": 0,
        "tables_missing": 0,
        "table_manifest_relpath": "tables/manifest.json",
    }

    if not dry_run:
        paper_dst.mkdir(parents=True, exist_ok=True)
        shutil.copy2(md_files[0], dst_md)
        shutil.copy2(v2_json_files[0], dst_v2)
        if copy_legacy_json and legacy_json_files:
            shutil.copy2(legacy_json_files[0], dst_legacy)

    stats["images_all"] = copy_images_dir(images_dir, dst_images, dry_run=dry_run)
    table_manifest, missing = build_table_manifest(parse_dir, table_items, dst_table, dry_run=dry_run)
    stats["tables_copied"] = sum(1 for item in table_manifest if item["source_exists"])
    stats["tables_missing"] = missing

    if inject_table_images and not dry_run:
        md_text = dst_md.read_text(encoding="utf-8")
        enhanced = inject_table_image_refs(md_text, table_manifest)
        if enhanced != md_text:
            dst_md.write_text(enhanced, encoding="utf-8")
            stats["tables_injected"] = sum(
                1 for e in table_manifest if e.get("source_exists") and e.get("normalized_relpath")
            )
        else:
            stats["tables_injected"] = 0
    else:
        stats["tables_injected"] = 0

    paper_manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "paper_token": paper_token,
        "source_paper_dir": str(src_paper_dir),
        "source_parse_dir": str(parse_dir),
        "normalized_paper_dir": str(paper_dst),
        "markdown_file": dst_md.name,
        "parse_json_file": dst_v2.name,
        "legacy_content_list_file": dst_legacy.name if copy_legacy_json and legacy_json_files else None,
        "images_count": stats["images_all"],
        "tables_detected": stats["tables_detected"],
        "tables_copied": stats["tables_copied"],
        "tables_missing": stats["tables_missing"],
    }

    if not dry_run:
        write_json(dst_table / "manifest.json", table_manifest)

    stats["table_manifest"] = table_manifest
    stats["paper_manifest"] = paper_manifest
    return stats


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Normalize raw MinerU parsed folders into processed-style paper folders."
    )
    parser.add_argument("input_dir", type=Path, help="Raw parsed root directory.")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output root directory. Default: <input_dir>_with_tables sibling.",
    )
    parser.add_argument(
        "--id-regex",
        default=r"\[(?P<id>A\d+-\d+)\]",
        help="Optional regex to extract paper id from each source folder name.",
    )
    parser.add_argument(
        "--name-template",
        default="{paper_id}",
        help="Output paper token template. Example: '{paper_id}' or '[{paper_id}]'.",
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
        "--strict-id",
        action="store_true",
        help="Skip folder when id cannot be extracted by --id-regex.",
    )
    parser.add_argument(
        "--copy-legacy-json",
        action="store_true",
        help="Copy *_content_list.json alongside the normalized parser JSON when available.",
    )
    parser.add_argument(
        "--summary-json",
        type=Path,
        default=None,
        help="Optional path to write dataset-level preprocess summary JSON.",
    )
    parser.add_argument(
        "--inject-table-images",
        action="store_true",
        help="Insert table image references into the output markdown before each <table> tag.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview actions without writing files.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    input_dir: Path = args.input_dir
    if not input_dir.exists() or not input_dir.is_dir():
        print(f"[FAIL] input_dir does not exist or is not a directory: {input_dir}")
        return 2

    include_pattern = re.compile(args.include_regex) if args.include_regex else None
    exclude_pattern = re.compile(args.exclude_regex) if args.exclude_regex else None

    output_dir = args.output or input_dir.parent / f"{input_dir.name}_with_tables"
    print(f"Input root: {input_dir}")
    print(f"Output root: {output_dir}")
    print("Output policy: keep one markdown + one parser json + full images + extracted tables + manifests")
    if args.dry_run:
        print("[DRY RUN]")
    print()

    totals: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_root": str(input_dir),
        "output_root": str(output_dir),
        "papers": 0,
        "images_all": 0,
        "tables_detected": 0,
        "tables_copied": 0,
        "tables_missing": 0,
        "skipped": 0,
        "paper_summaries": [],
    }

    for item in sorted(input_dir.iterdir()):
        if not item.is_dir():
            continue
        if include_pattern and not include_pattern.search(item.name):
            continue
        if exclude_pattern and exclude_pattern.search(item.name):
            continue

        paper_id = extract_paper_id(item.name, args.id_regex)
        if not paper_id:
            if args.strict_id:
                print(f"  [SKIP] paper id cannot be extracted: {item.name}")
                totals["skipped"] += 1
                continue
            paper_id = infer_paper_id(item.name)

        try:
            paper_token = args.name_template.format(paper_id=paper_id)
        except Exception as exc:  # noqa: BLE001
            print(f"[FAIL] invalid --name-template: {exc}")
            return 2

        stats = reorganize_one_paper(
            src_paper_dir=item,
            dst_root=output_dir,
            paper_token=paper_token,
            dry_run=args.dry_run,
            copy_legacy_json=args.copy_legacy_json,
            inject_table_images=args.inject_table_images,
        )
        if stats is None:
            totals["skipped"] += 1
            continue

        totals["papers"] += 1
        totals["images_all"] += stats["images_all"]
        totals["tables_detected"] += stats["tables_detected"]
        totals["tables_copied"] += stats["tables_copied"]
        totals["tables_missing"] += stats["tables_missing"]
        totals["paper_summaries"].append(
            {
                "paper_token": paper_token,
                "source_paper_dir": stats["source_paper_dir"],
                "normalized_paper_dir": stats["normalized_paper_dir"],
                "images_all": stats["images_all"],
                "tables_detected": stats["tables_detected"],
                "tables_copied": stats["tables_copied"],
                "tables_missing": stats["tables_missing"],
            }
        )
        print(
            f"  [OK] {paper_token}: "
            f"{stats['images_all']} images kept, "
            f"{stats['tables_copied']}/{stats['tables_detected']} tables extracted"
        )

    print("\n=== Done ===")
    print(f"Papers processed: {totals['papers']}")
    print(f"Papers skipped: {totals['skipped']}")
    print(f"Images kept: {totals['images_all']}")
    print(f"Table images detected: {totals['tables_detected']}")
    print(f"Table images copied: {totals['tables_copied']}")
    print(f"Table images missing: {totals['tables_missing']}")

    summary_path = args.summary_json
    if summary_path is None and not args.dry_run:
        summary_path = output_dir / "preprocess_summary.json"
    if summary_path and not args.dry_run:
        write_json(summary_path, totals)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
