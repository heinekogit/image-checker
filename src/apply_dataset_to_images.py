from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from compare_modified_regions import IMAGE_EXTENSIONS, ROOT_DIR, image_paths, load_color


DEFAULT_DATASET = ROOT_DIR / "output" / "paired_dataset" / "dataset.csv"
DEFAULT_TARGET = ROOT_DIR / "tests" / "B_original" / "image"
DEFAULT_OUTPUT = ROOT_DIR / "output" / "b_initial_apply"


@dataclass(frozen=True)
class Template:
    sample_id: str
    source_file: str
    path: Path
    image: np.ndarray
    area: int


@dataclass(frozen=True)
class Candidate:
    target_file: str
    sample_id: str
    template_source_file: str
    score: float
    x: int
    y: int
    width: int
    height: int


def load_templates(dataset_csv: Path, max_templates: int, min_template_area: int) -> list[Template]:
    with dataset_csv.open("r", newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))

    rows.sort(key=lambda row: int(row["area"]), reverse=True)
    templates: list[Template] = []
    for row in rows:
        area = int(row["area"])
        if area < min_template_area:
            continue

        path = Path(row["original_crop"])
        image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if image is None:
            continue

        templates.append(
            Template(
                sample_id=row["sample_id"],
                source_file=row["source_file"],
                path=path,
                image=preprocess(image),
                area=area,
            )
        )
        if len(templates) >= max_templates:
            break

    if not templates:
        raise ValueError("No usable templates found.")
    return templates


def preprocess(gray: np.ndarray) -> np.ndarray:
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    edges = cv2.Canny(blurred, 60, 160)
    return edges


def match_template(
    target_edges: np.ndarray,
    template: Template,
    scales: list[float],
    min_score: float,
    work_scale: float,
) -> Candidate | None:
    best: Candidate | None = None
    for scale in scales:
        width = max(16, round(template.image.shape[1] * scale * work_scale))
        height = max(16, round(template.image.shape[0] * scale * work_scale))
        if width >= target_edges.shape[1] or height >= target_edges.shape[0]:
            continue

        scaled = cv2.resize(template.image, (width, height), interpolation=cv2.INTER_AREA)
        if cv2.countNonZero(scaled) < 30:
            continue

        result = cv2.matchTemplate(target_edges, scaled, cv2.TM_CCOEFF_NORMED)
        _, score, _, location = cv2.minMaxLoc(result)
        if score < min_score:
            continue

        candidate = Candidate(
            target_file="",
            sample_id=template.sample_id,
            template_source_file=template.source_file,
            score=float(score),
            x=round(location[0] / work_scale),
            y=round(location[1] / work_scale),
            width=round(width / work_scale),
            height=round(height / work_scale),
        )
        if best is None or candidate.score > best.score:
            best = candidate
    return best


def suppress_overlaps(candidates: list[Candidate], overlap_threshold: float) -> list[Candidate]:
    kept: list[Candidate] = []
    for candidate in sorted(candidates, key=lambda item: item.score, reverse=True):
        if all(iou(candidate, existing) < overlap_threshold for existing in kept):
            kept.append(candidate)
    return kept


def iou(a: Candidate, b: Candidate) -> float:
    ax2 = a.x + a.width
    ay2 = a.y + a.height
    bx2 = b.x + b.width
    by2 = b.y + b.height

    ix1 = max(a.x, b.x)
    iy1 = max(a.y, b.y)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    intersection = max(ix2 - ix1, 0) * max(iy2 - iy1, 0)
    if intersection == 0:
        return 0.0

    union = a.width * a.height + b.width * b.height - intersection
    return intersection / float(union)


def draw_candidates(image: np.ndarray, candidates: list[Candidate], output_path: Path) -> None:
    preview = image.copy()
    for index, candidate in enumerate(candidates, start=1):
        top_left = (candidate.x, candidate.y)
        bottom_right = (candidate.x + candidate.width, candidate.y + candidate.height)
        cv2.rectangle(preview, top_left, bottom_right, (0, 0, 255), 3)
        cv2.putText(
            preview,
            f"{index}:{candidate.score:.2f}",
            (candidate.x, max(candidate.y - 8, 20)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 0, 255),
            2,
            cv2.LINE_AA,
        )
    cv2.imwrite(str(output_path), preview)


def apply_dataset(
    dataset_csv: Path,
    target_dir: Path,
    output_dir: Path,
    max_templates: int,
    min_template_area: int,
    min_score: float,
    per_page: int,
    overlap_threshold: float,
    work_scale: float,
    max_pages: int | None,
) -> list[Candidate]:
    templates = load_templates(dataset_csv, max_templates=max_templates, min_template_area=min_template_area)
    targets = image_paths(target_dir)
    if not targets:
        raise ValueError(f"No target images found: {target_dir}")

    previews_dir = output_dir / "previews"
    previews_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    scales = [0.75, 0.85, 1.0, 1.15, 1.30]
    all_candidates: list[Candidate] = []
    target_items = sorted(targets.items())
    if max_pages is not None:
        target_items = target_items[:max_pages]

    for target_name, target_path in target_items:
        target_image = load_color(target_path)
        target_gray = cv2.cvtColor(target_image, cv2.COLOR_BGR2GRAY)
        if work_scale != 1.0:
            target_gray = cv2.resize(target_gray, None, fx=work_scale, fy=work_scale, interpolation=cv2.INTER_AREA)
        target_edges = preprocess(target_gray)

        page_candidates: list[Candidate] = []
        for template in templates:
            candidate = match_template(
                target_edges,
                template,
                scales=scales,
                min_score=min_score,
                work_scale=work_scale,
            )
            if candidate is not None:
                page_candidates.append(
                    Candidate(
                        target_file=target_name,
                        sample_id=candidate.sample_id,
                        template_source_file=candidate.template_source_file,
                        score=candidate.score,
                        x=candidate.x,
                        y=candidate.y,
                        width=candidate.width,
                        height=candidate.height,
                    )
                )

        page_candidates = suppress_overlaps(page_candidates, overlap_threshold=overlap_threshold)[:per_page]
        if page_candidates:
            draw_candidates(target_image, page_candidates, previews_dir / f"{Path(target_name).stem}_candidates.jpg")
            all_candidates.extend(page_candidates)

    with (output_dir / "matches.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["target_file", "rank_on_page", "sample_id", "template_source_file", "score", "x", "y", "width", "height"])
        last_file = None
        rank = 0
        for candidate in all_candidates:
            if candidate.target_file != last_file:
                last_file = candidate.target_file
                rank = 1
            else:
                rank += 1
            writer.writerow(
                [
                    candidate.target_file,
                    rank,
                    candidate.sample_id,
                    candidate.template_source_file,
                    f"{candidate.score:.6f}",
                    candidate.x,
                    candidate.y,
                    candidate.width,
                    candidate.height,
                ]
            )

    return all_candidates


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply paired dataset crops to another image folder by template matching.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-templates", type=int, default=50)
    parser.add_argument("--min-template-area", type=int, default=1200)
    parser.add_argument("--min-score", type=float, default=0.22)
    parser.add_argument("--per-page", type=int, default=5)
    parser.add_argument("--overlap-threshold", type=float, default=0.25)
    parser.add_argument("--work-scale", type=float, default=0.5)
    parser.add_argument("--max-pages", type=int, default=None)
    args = parser.parse_args()

    candidates = apply_dataset(
        dataset_csv=args.dataset,
        target_dir=args.target,
        output_dir=args.output,
        max_templates=args.max_templates,
        min_template_area=args.min_template_area,
        min_score=args.min_score,
        per_page=args.per_page,
        overlap_threshold=args.overlap_threshold,
        work_scale=args.work_scale,
        max_pages=args.max_pages,
    )
    pages = {candidate.target_file for candidate in candidates}
    print(f"candidate_pages: {len(pages)}")
    print(f"candidates: {len(candidates)}")
    print(f"saved: {args.output}")


if __name__ == "__main__":
    main()
