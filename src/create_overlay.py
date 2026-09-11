from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from compare_modified_regions import ROOT_DIR, load_color


DEFAULT_IMAGE = ROOT_DIR / "tests" / "B_original" / "image" / "i-023.jpg"
DEFAULT_OUTPUT = ROOT_DIR / "output" / "overlay_poc"


def read_operations(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("operations"), list):
        return data["operations"]
    raise ValueError("Operations JSON must be a list or an object with an operations list.")


def mask_for_operation(shape: tuple[int, int], operation: dict[str, Any]) -> np.ndarray:
    height, width = shape
    mask = np.zeros((height, width), dtype=np.uint8)
    x = int(operation["x"])
    y = int(operation["y"])
    op_width = int(operation.get("width", operation.get("radius", 80)))
    op_height = int(operation.get("height", operation.get("radius", 80)))
    angle = float(operation.get("angle", 0))
    shape_name = operation.get("shape", "ellipse")

    if shape_name == "rect":
        rect = ((float(x), float(y)), (float(op_width), float(op_height)), angle)
        points = cv2.boxPoints(rect).astype(np.int32)
        cv2.fillConvexPoly(mask, points, 255)
    elif shape_name == "circle":
        radius = max(op_width, op_height) // 2
        cv2.circle(mask, (x, y), radius, 255, -1)
    else:
        axes = (max(op_width // 2, 1), max(op_height // 2, 1))
        cv2.ellipse(mask, (x, y), axes, angle, 0, 360, 255, -1)

    if operation.get("tool") == "white_glow":
        glow = int(operation.get("glow", operation.get("strength", 24)))
        if glow > 0:
            kernel = glow * 2 + 1
            if kernel % 2 == 0:
                kernel += 1
            glow_mask = cv2.GaussianBlur(mask, (kernel, kernel), 0)
            mask = np.maximum(mask, glow_mask)

    feather = int(operation.get("feather", 0))
    if feather > 0 and operation.get("tool") != "white_glow":
        kernel = feather * 2 + 1
        if kernel % 2 == 0:
            kernel += 1
        mask = cv2.GaussianBlur(mask, (kernel, kernel), 0)

    opacity = float(operation.get("opacity", 1.0))
    opacity = min(max(opacity, 0.0), 1.0)
    return np.clip(mask.astype(np.float32) * opacity, 0, 255).astype(np.uint8)


def parse_color(value: Any, default: tuple[int, int, int]) -> tuple[int, int, int]:
    if value is None:
        return default
    if isinstance(value, str):
        text = value.strip().lstrip("#")
        if len(text) == 6:
            red = int(text[0:2], 16)
            green = int(text[2:4], 16)
            blue = int(text[4:6], 16)
            return blue, green, red
    if isinstance(value, list) and len(value) == 3:
        red, green, blue = (int(channel) for channel in value)
        return blue, green, red
    raise ValueError(f"Unsupported color value: {value}")


def mosaic(image: np.ndarray, block_size: int) -> np.ndarray:
    height, width = image.shape[:2]
    small_width = max(1, width // block_size)
    small_height = max(1, height // block_size)
    small = cv2.resize(image, (small_width, small_height), interpolation=cv2.INTER_LINEAR)
    return cv2.resize(small, (width, height), interpolation=cv2.INTER_NEAREST)


def operation_layer(original: np.ndarray, operation: dict[str, Any], alpha: np.ndarray) -> np.ndarray:
    tool = operation.get("tool", "white_fill")
    layer_rgb = np.zeros_like(original)

    if tool == "black_fill":
        color = parse_color(operation.get("color"), (0, 0, 0))
        layer_rgb[:, :] = color
    elif tool == "mosaic":
        block_size = max(int(operation.get("block_size", operation.get("strength", 12))), 2)
        layer_rgb = mosaic(original, block_size)
    else:
        color = parse_color(operation.get("color"), (255, 255, 255))
        layer_rgb[:, :] = color

    return np.dstack([layer_rgb, alpha])


def alpha_composite(base: np.ndarray, top: np.ndarray) -> np.ndarray:
    base_rgb = base[:, :, :3].astype(np.float32)
    base_alpha = base[:, :, 3:4].astype(np.float32) / 255.0
    top_rgb = top[:, :, :3].astype(np.float32)
    top_alpha = top[:, :, 3:4].astype(np.float32) / 255.0

    out_alpha = top_alpha + base_alpha * (1.0 - top_alpha)
    safe_alpha = np.where(out_alpha == 0, 1.0, out_alpha)
    out_rgb = (top_rgb * top_alpha + base_rgb * base_alpha * (1.0 - top_alpha)) / safe_alpha
    return np.dstack([out_rgb, out_alpha * 255.0]).clip(0, 255).astype(np.uint8)


def overlay_on_image(original: np.ndarray, overlay: np.ndarray) -> np.ndarray:
    alpha = overlay[:, :, 3:4].astype(np.float32) / 255.0
    original_float = original.astype(np.float32)
    overlay_float = overlay[:, :, :3].astype(np.float32)
    return (overlay_float * alpha + original_float * (1.0 - alpha)).clip(0, 255).astype(np.uint8)


def create_overlay(image_path: Path, operations_path: Path, output_dir: Path) -> tuple[Path, Path, Path]:
    original = load_color(image_path)
    height, width = original.shape[:2]
    overlay = np.zeros((height, width, 4), dtype=np.uint8)
    operations = read_operations(operations_path)

    for operation in operations:
        alpha = mask_for_operation((height, width), operation)
        layer = operation_layer(original, operation, alpha)
        overlay = alpha_composite(overlay, layer)

    output_dir.mkdir(parents=True, exist_ok=True)
    stem = image_path.stem
    overlay_path = output_dir / f"{stem}_alpha.png"
    preview_path = output_dir / f"{stem}_preview.jpg"
    log_path = output_dir / f"{stem}_ops.json"

    preview = overlay_on_image(original, overlay)
    cv2.imwrite(str(overlay_path), overlay)
    cv2.imwrite(str(preview_path), preview)
    with log_path.open("w", encoding="utf-8") as file:
        json.dump(
            {
                "image": str(image_path),
                "overlay": str(overlay_path),
                "preview": str(preview_path),
                "operations": operations,
            },
            file,
            ensure_ascii=False,
            indent=2,
        )

    return overlay_path, preview_path, log_path


def write_sample_operations(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "operations": [
            {
                "tool": "white_fill",
                "shape": "ellipse",
                "x": 540,
                "y": 760,
                "width": 160,
                "height": 70,
                "angle": -10,
                "opacity": 1.0,
                "feather": 2,
            },
            {
                "tool": "white_glow",
                "shape": "ellipse",
                "x": 620,
                "y": 900,
                "width": 180,
                "height": 90,
                "angle": 8,
                "opacity": 1.0,
                "glow": 24,
            },
        ]
    }
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create same-size transparent overlay PNG from correction operations.")
    parser.add_argument("--image", type=Path, default=DEFAULT_IMAGE)
    parser.add_argument("--operations", type=Path, default=DEFAULT_OUTPUT / "sample_ops.json")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--init-sample", action="store_true", help="Write a sample operations JSON before rendering.")
    args = parser.parse_args()

    if args.init_sample or not args.operations.exists():
        write_sample_operations(args.operations)

    overlay_path, preview_path, log_path = create_overlay(args.image, args.operations, args.output)
    print(f"overlay: {overlay_path}")
    print(f"preview: {preview_path}")
    print(f"log: {log_path}")


if __name__ == "__main__":
    main()
