from __future__ import annotations

import argparse
import csv
from pathlib import Path

import cv2

from compare_modified_regions import (
    DEFAULT_MODIFIED,
    DEFAULT_ORIGINAL,
    IMAGE_EXTENSIONS,
    ROOT_DIR,
    build_diff_mask,
    expand_box,
    find_regions,
    image_paths,
    load_color,
)


DEFAULT_OUTPUT = ROOT_DIR / "output" / "paired_dataset"


def write_dataset(
    original_dir: Path,
    modified_dir: Path,
    output_dir: Path,
    threshold: int,
    blur_size: int,
    morph_size: int,
    dilate_iterations: int,
    min_area: int,
    min_diff_pixels: int,
    padding: int,
    global_change_ratio: float,
) -> list[dict[str, object]]:
    original_paths = image_paths(original_dir)
    modified_paths = image_paths(modified_dir)
    common_names = sorted(set(original_paths) & set(modified_paths))
    if not common_names:
        raise ValueError("No matching image file names found.")

    original_out = output_dir / "original"
    modified_out = output_dir / "modified"
    mask_out = output_dir / "mask"
    preview_out = output_dir / "preview"
    for directory in (original_out, modified_out, mask_out, preview_out):
        directory.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, object]] = []
    for file_name in common_names:
        original = load_color(original_paths[file_name])
        modified = load_color(modified_paths[file_name])
        if original.shape != modified.shape:
            continue

        image_height, image_width = original.shape[:2]
        mask = build_diff_mask(
            original,
            modified,
            threshold=threshold,
            blur_size=blur_size,
            morph_size=morph_size,
            dilate_iterations=dilate_iterations,
        )

        total_diff_pixels = int(cv2.countNonZero(mask))
        page_pixels = image_width * image_height
        if total_diff_pixels == 0 or total_diff_pixels / float(page_pixels) >= global_change_ratio:
            continue

        raw_regions = find_regions(mask, min_area=min_area, min_diff_pixels=min_diff_pixels)
        if not raw_regions:
            continue

        page_preview = original.copy()
        for region_id, (x, y, width, height, area, diff_pixels, diff_ratio) in enumerate(raw_regions, start=1):
            expanded_x, expanded_y, expanded_width, expanded_height = expand_box(
                x,
                y,
                width,
                height,
                image_width,
                image_height,
                padding,
            )
            sample_id = f"{Path(file_name).stem}_{region_id:03d}"
            original_crop_path = original_out / f"{sample_id}.jpg"
            modified_crop_path = modified_out / f"{sample_id}.jpg"
            mask_crop_path = mask_out / f"{sample_id}.png"

            original_crop = original[
                expanded_y : expanded_y + expanded_height,
                expanded_x : expanded_x + expanded_width,
            ]
            modified_crop = modified[
                expanded_y : expanded_y + expanded_height,
                expanded_x : expanded_x + expanded_width,
            ]
            mask_crop = mask[
                expanded_y : expanded_y + expanded_height,
                expanded_x : expanded_x + expanded_width,
            ]

            cv2.imwrite(str(original_crop_path), original_crop)
            cv2.imwrite(str(modified_crop_path), modified_crop)
            cv2.imwrite(str(mask_crop_path), mask_crop)

            cv2.rectangle(page_preview, (x, y), (x + width, y + height), (0, 0, 255), 3)
            cv2.putText(
                page_preview,
                str(region_id),
                (x, max(y - 8, 20)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 0, 255),
                2,
                cv2.LINE_AA,
            )

            rows.append(
                {
                    "sample_id": sample_id,
                    "source_file": file_name,
                    "region_id": region_id,
                    "page_width": image_width,
                    "page_height": image_height,
                    "x": x,
                    "y": y,
                    "width": width,
                    "height": height,
                    "area": area,
                    "diff_pixels": diff_pixels,
                    "diff_ratio": f"{diff_ratio:.6f}",
                    "expanded_x": expanded_x,
                    "expanded_y": expanded_y,
                    "expanded_width": expanded_width,
                    "expanded_height": expanded_height,
                    "label": "insufficient_censoring",
                    "review_status": "confirmed_by_batch",
                    "original_crop": str(original_crop_path),
                    "modified_crop": str(modified_crop_path),
                    "mask_crop": str(mask_crop_path),
                }
            )

        cv2.imwrite(str(preview_out / f"{Path(file_name).stem}_diff.jpg"), page_preview)

    csv_path = output_dir / "dataset.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()) if rows else ["sample_id"])
        writer.writeheader()
        writer.writerows(rows)

    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Build paired original/modified/mask crops from before/after images.")
    parser.add_argument("--original", type=Path, default=DEFAULT_ORIGINAL)
    parser.add_argument("--modified", type=Path, default=DEFAULT_MODIFIED)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--threshold", type=int, default=18)
    parser.add_argument("--blur-size", type=int, default=3)
    parser.add_argument("--morph-size", type=int, default=5)
    parser.add_argument("--dilate-iterations", type=int, default=2)
    parser.add_argument("--min-area", type=int, default=150)
    parser.add_argument("--min-diff-pixels", type=int, default=40)
    parser.add_argument("--padding", type=int, default=48)
    parser.add_argument("--global-change-ratio", type=float, default=0.20)
    args = parser.parse_args()

    rows = write_dataset(
        original_dir=args.original,
        modified_dir=args.modified,
        output_dir=args.output,
        threshold=args.threshold,
        blur_size=args.blur_size,
        morph_size=args.morph_size,
        dilate_iterations=args.dilate_iterations,
        min_area=args.min_area,
        min_diff_pixels=args.min_diff_pixels,
        padding=args.padding,
        global_change_ratio=args.global_change_ratio,
    )
    print(f"samples: {len(rows)}")
    print(f"saved: {args.output}")


if __name__ == "__main__":
    main()
