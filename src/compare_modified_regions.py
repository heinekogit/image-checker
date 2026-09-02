from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_ORIGINAL = ROOT_DIR / "tests" / "A_original" / "image"
DEFAULT_MODIFIED = ROOT_DIR / "tests" / "A_modified" / "image"
DEFAULT_OUTPUT = ROOT_DIR / "output" / "diff_test"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}


@dataclass(frozen=True)
class DiffRegion:
    file_name: str
    region_id: int
    page_width: int
    page_height: int
    x: int
    y: int
    width: int
    height: int
    area: int
    diff_pixels: int
    diff_ratio: float
    expanded_x: int
    expanded_y: int
    expanded_width: int
    expanded_height: int
    crop_path: Path


def image_paths(directory: Path) -> dict[str, Path]:
    if not directory.exists():
        raise FileNotFoundError(f"Directory not found: {directory}")

    paths: dict[str, Path] = {}
    for path in sorted(directory.iterdir()):
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            paths[path.name] = path
    return paths


def load_color(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Could not read image: {path}")
    return image


def expand_box(
    x: int,
    y: int,
    width: int,
    height: int,
    image_width: int,
    image_height: int,
    padding: int,
) -> tuple[int, int, int, int]:
    left = max(x - padding, 0)
    top = max(y - padding, 0)
    right = min(x + width + padding, image_width)
    bottom = min(y + height + padding, image_height)
    return left, top, right - left, bottom - top


def build_diff_mask(
    original: np.ndarray,
    modified: np.ndarray,
    threshold: int,
    blur_size: int,
    morph_size: int,
    dilate_iterations: int,
) -> np.ndarray:
    diff = cv2.absdiff(original, modified)
    gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)

    if blur_size > 1:
        if blur_size % 2 == 0:
            blur_size += 1
        gray = cv2.GaussianBlur(gray, (blur_size, blur_size), 0)

    _, mask = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)

    if morph_size > 1:
        kernel = np.ones((morph_size, morph_size), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

    if dilate_iterations > 0:
        kernel = np.ones((3, 3), np.uint8)
        mask = cv2.dilate(mask, kernel, iterations=dilate_iterations)

    return mask


def find_regions(
    mask: np.ndarray,
    min_area: int,
    min_diff_pixels: int,
) -> list[tuple[int, int, int, int, int, int, float]]:
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    regions: list[tuple[int, int, int, int, int, int, float]] = []

    for contour in contours:
        x, y, width, height = cv2.boundingRect(contour)
        area = width * height
        if area < min_area:
            continue

        roi = mask[y : y + height, x : x + width]
        diff_pixels = int(cv2.countNonZero(roi))
        if diff_pixels < min_diff_pixels:
            continue

        diff_ratio = diff_pixels / float(area)
        regions.append((x, y, width, height, area, diff_pixels, diff_ratio))

    regions.sort(key=lambda item: (item[1], item[0]))
    return regions


def draw_preview(
    original: np.ndarray,
    regions: list[DiffRegion],
    output_path: Path,
) -> None:
    preview = original.copy()
    for region in regions:
        top_left = (region.x, region.y)
        bottom_right = (region.x + region.width, region.y + region.height)
        cv2.rectangle(preview, top_left, bottom_right, (0, 0, 255), 3)
        cv2.putText(
            preview,
            str(region.region_id),
            (region.x, max(region.y - 8, 20)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 0, 255),
            2,
            cv2.LINE_AA,
        )
    cv2.imwrite(str(output_path), preview)


def compare_pair(
    file_name: str,
    original_path: Path,
    modified_path: Path,
    previews_dir: Path,
    samples_dir: Path,
    threshold: int,
    blur_size: int,
    morph_size: int,
    dilate_iterations: int,
    min_area: int,
    min_diff_pixels: int,
    padding: int,
    global_change_ratio: float,
) -> tuple[list[DiffRegion], str]:
    original = load_color(original_path)
    modified = load_color(modified_path)

    if original.shape != modified.shape:
        return [], "size_mismatch"

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
    if total_diff_pixels == 0:
        return [], "unchanged"

    page_pixels = image_width * image_height
    if total_diff_pixels / float(page_pixels) >= global_change_ratio:
        return [], "global_change"

    raw_regions = find_regions(mask, min_area=min_area, min_diff_pixels=min_diff_pixels)
    if not raw_regions:
        return [], "below_threshold"

    regions: list[DiffRegion] = []
    for index, (x, y, width, height, area, diff_pixels, diff_ratio) in enumerate(raw_regions, start=1):
        expanded_x, expanded_y, expanded_width, expanded_height = expand_box(
            x,
            y,
            width,
            height,
            image_width,
            image_height,
            padding,
        )
        crop = original[
            expanded_y : expanded_y + expanded_height,
            expanded_x : expanded_x + expanded_width,
        ]
        crop_path = samples_dir / f"{Path(file_name).stem}_{index:03d}.jpg"
        cv2.imwrite(str(crop_path), crop)

        regions.append(
            DiffRegion(
                file_name=file_name,
                region_id=index,
                page_width=image_width,
                page_height=image_height,
                x=x,
                y=y,
                width=width,
                height=height,
                area=area,
                diff_pixels=diff_pixels,
                diff_ratio=diff_ratio,
                expanded_x=expanded_x,
                expanded_y=expanded_y,
                expanded_width=expanded_width,
                expanded_height=expanded_height,
                crop_path=crop_path,
            )
        )

    preview_path = previews_dir / f"{Path(file_name).stem}_diff.jpg"
    draw_preview(original, regions, preview_path)
    return regions, "changed"


def write_regions_csv(path: Path, regions: list[DiffRegion]) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(
            [
                "file",
                "page_width",
                "page_height",
                "region_id",
                "x",
                "y",
                "width",
                "height",
                "area",
                "diff_pixels",
                "diff_ratio",
                "x_norm",
                "y_norm",
                "width_norm",
                "height_norm",
                "expanded_x",
                "expanded_y",
                "expanded_width",
                "expanded_height",
                "label",
                "review_status",
                "crop_path",
            ]
        )
        for region in regions:
            writer.writerow(
                [
                    region.file_name,
                    region.page_width,
                    region.page_height,
                    region.region_id,
                    region.x,
                    region.y,
                    region.width,
                    region.height,
                    region.area,
                    region.diff_pixels,
                    f"{region.diff_ratio:.6f}",
                    f"{region.x / region.page_width:.8f}",
                    f"{region.y / region.page_height:.8f}",
                    f"{region.width / region.page_width:.8f}",
                    f"{region.height / region.page_height:.8f}",
                    region.expanded_x,
                    region.expanded_y,
                    region.expanded_width,
                    region.expanded_height,
                    "unknown",
                    "auto_detected",
                    str(region.crop_path),
                ]
            )


def write_pages_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "file",
                "status",
                "region_count",
                "original_path",
                "modified_path",
                "preview_path",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def compare_directories(
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
) -> tuple[list[DiffRegion], list[dict[str, object]]]:
    original_paths = image_paths(original_dir)
    modified_paths = image_paths(modified_dir)

    common_names = sorted(set(original_paths) & set(modified_paths))
    if not common_names:
        raise ValueError("No matching image file names found.")

    previews_dir = output_dir / "previews"
    samples_dir = output_dir / "samples"
    previews_dir.mkdir(parents=True, exist_ok=True)
    samples_dir.mkdir(parents=True, exist_ok=True)

    all_regions: list[DiffRegion] = []
    page_rows: list[dict[str, object]] = []
    for file_name in common_names:
        regions, status = compare_pair(
            file_name=file_name,
            original_path=original_paths[file_name],
            modified_path=modified_paths[file_name],
            previews_dir=previews_dir,
            samples_dir=samples_dir,
            threshold=threshold,
            blur_size=blur_size,
            morph_size=morph_size,
            dilate_iterations=dilate_iterations,
            min_area=min_area,
            min_diff_pixels=min_diff_pixels,
            padding=padding,
            global_change_ratio=global_change_ratio,
        )
        all_regions.extend(regions)
        page_rows.append(
            {
                "file": file_name,
                "status": status,
                "region_count": len(regions),
                "original_path": str(original_paths[file_name]),
                "modified_path": str(modified_paths[file_name]),
                "preview_path": str(previews_dir / f"{Path(file_name).stem}_diff.jpg") if regions else "",
            }
        )

    write_regions_csv(output_dir / "regions.csv", all_regions)
    write_pages_csv(output_dir / "pages.csv", page_rows)
    return all_regions, page_rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract edited regions from before/after image folders.")
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

    regions, page_rows = compare_directories(
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

    changed_pages = sum(1 for row in page_rows if row["status"] == "changed")
    print(f"compared: {len(page_rows)}")
    print(f"changed_pages: {changed_pages}")
    print(f"regions: {len(regions)}")
    print(f"saved: {args.output}")


if __name__ == "__main__":
    main()
