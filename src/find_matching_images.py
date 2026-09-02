from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_QUERY = ROOT_DIR / "tests" / "fixtures" / "images" / "query" / "hip_01.jpg"
DEFAULT_CANDIDATES = ROOT_DIR / "tests" / "fixtures" / "images" / "candidates"
DEFAULT_OUTPUT = ROOT_DIR / "output" / "match_test"


@dataclass(frozen=True)
class MatchResult:
    path: Path
    score: float
    scale: float
    x: int
    y: int
    width: int
    height: int


def load_gray(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise ValueError(f"Could not read image: {path}")
    return image


def ink_mask(gray: np.ndarray) -> np.ndarray:
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    _, binary = cv2.threshold(blurred, 100, 255, cv2.THRESH_BINARY_INV)
    kernel = np.ones((2, 2), np.uint8)
    return cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)


def crop_to_ink(mask: np.ndarray, padding: int = 8) -> np.ndarray:
    points = cv2.findNonZero(mask)
    if points is None:
        raise ValueError("Query image has no detectable ink pixels")

    x, y, width, height = cv2.boundingRect(points)
    left = max(x - padding, 0)
    top = max(y - padding, 0)
    right = min(x + width + padding, mask.shape[1])
    bottom = min(y + height + padding, mask.shape[0])
    return mask[top:bottom, left:right]


def match_one(query_mask: np.ndarray, candidate_path: Path, scales: list[float]) -> MatchResult:
    candidate_gray = load_gray(candidate_path)
    candidate_mask = ink_mask(candidate_gray)
    distance_to_ink = cv2.distanceTransform(255 - candidate_mask, cv2.DIST_L2, 3)

    best: MatchResult | None = None
    for scale in scales:
        width = max(8, round(query_mask.shape[1] * scale))
        height = max(8, round(query_mask.shape[0] * scale))
        if width >= candidate_mask.shape[1] or height >= candidate_mask.shape[0]:
            continue

        template = cv2.resize(query_mask, (width, height), interpolation=cv2.INTER_AREA)
        active = cv2.countNonZero(template)
        if active < 20:
            continue

        template_float = (template > 0).astype(np.float32)
        candidate_float = (candidate_mask > 0).astype(np.float32)
        result = cv2.matchTemplate(distance_to_ink, template_float, cv2.TM_CCORR)
        result = result / float(active)
        proximity = 1.0 / (1.0 + result)

        patch_ink = cv2.matchTemplate(
            candidate_float,
            np.ones((height, width), dtype=np.float32),
            cv2.TM_CCORR,
        )
        query_density = active / float(width * height)
        patch_density = patch_ink / float(width * height)
        density_penalty = np.exp(-np.abs(patch_density - query_density) * 20.0)
        score_map = proximity * density_penalty

        _, score, _, location = cv2.minMaxLoc(score_map)
        match = MatchResult(
            path=candidate_path,
            score=float(score),
            scale=scale,
            x=int(location[0]),
            y=int(location[1]),
            width=width,
            height=height,
        )
        if best is None or match.score > best.score:
            best = match

    if best is None:
        raise ValueError(f"No valid scale for candidate: {candidate_path}")
    return best


def draw_match(result: MatchResult, output_dir: Path) -> Path:
    image = cv2.imread(str(result.path), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Could not read image: {result.path}")

    top_left = (result.x, result.y)
    bottom_right = (result.x + result.width, result.y + result.height)
    cv2.rectangle(image, top_left, bottom_right, (0, 0, 255), 3)
    cv2.putText(
        image,
        f"{result.score:.3f}",
        (result.x, max(result.y - 10, 20)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (0, 0, 255),
        2,
        cv2.LINE_AA,
    )

    output_path = output_dir / f"{result.path.stem}_match.jpg"
    cv2.imwrite(str(output_path), image)
    return output_path


def find_matches(query_path: Path, candidates_dir: Path, output_dir: Path, top: int) -> list[MatchResult]:
    query_mask = crop_to_ink(ink_mask(load_gray(query_path)))
    candidate_paths = sorted(candidates_dir.glob("*.jpg"))
    if not candidate_paths:
        raise ValueError(f"No candidate jpg files found: {candidates_dir}")

    scales = [round(0.50 + i * 0.05, 2) for i in range(35)]
    results = [match_one(query_mask, path, scales) for path in candidate_paths]
    results.sort(key=lambda item: item.score, reverse=True)

    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "match_results.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["rank", "file", "score", "scale", "x", "y", "width", "height"])
        for rank, result in enumerate(results, start=1):
            writer.writerow(
                [
                    rank,
                    result.path.name,
                    f"{result.score:.6f}",
                    f"{result.scale:.2f}",
                    result.x,
                    result.y,
                    result.width,
                    result.height,
                ]
            )

    for result in results[:top]:
        draw_match(result, output_dir)

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Find candidate images similar to a query image.")
    parser.add_argument("--query", type=Path, default=DEFAULT_QUERY)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--top", type=int, default=5)
    args = parser.parse_args()

    results = find_matches(args.query, args.candidates, args.output, args.top)
    for rank, result in enumerate(results, start=1):
        print(
            f"{rank:02d} {result.path.name} "
            f"score={result.score:.4f} scale={result.scale:.2f} "
            f"box=({result.x},{result.y},{result.width},{result.height})"
        )
    print(f"saved: {args.output}")


if __name__ == "__main__":
    main()
