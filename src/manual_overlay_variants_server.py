from __future__ import annotations

import argparse
import json
import mimetypes
import shutil
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from compare_modified_regions import IMAGE_EXTENSIONS, ROOT_DIR, image_paths
from create_overlay import create_overlay


DEFAULT_IMAGES = ROOT_DIR / "tests" / "B_original" / "image"
DEFAULT_OUTPUT = ROOT_DIR / "output" / "manual_overlay_variants"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8002


INDEX_HTML = r"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Manual Overlay Variants</title>
  <style>
    :root {
      color-scheme: light;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #eef2f3;
      color: #1e2930;
    }
    body { margin: 0; height: 100vh; overflow: hidden; }
    .app {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 380px;
      height: 100vh;
      min-height: 0;
    }
    .stage {
      min-width: 0;
      min-height: 0;
      padding: 16px;
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
      gap: 12px;
      box-sizing: border-box;
    }
    .topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      font-size: 14px;
    }
    .image-wrap {
      min-height: 0;
      height: 100%;
      overflow: auto;
      scrollbar-gutter: stable;
      background: #d8e0e2;
      border: 1px solid #8b9aa2;
      padding: 16px;
      box-sizing: border-box;
    }
    .canvas-box {
      position: relative;
      width: fit-content;
      height: fit-content;
      margin: 0 auto;
      line-height: 0;
      background: white;
      box-shadow: 0 1px 8px rgba(0, 0, 0, 0.18);
    }
    #pageImage { display: block; max-width: none; user-select: none; }
    #canvas { position: absolute; inset: 0; cursor: crosshair; }
    aside {
      border-left: 1px solid #8b9aa2;
      background: #f8fafb;
      padding: 16px;
      overflow: auto;
    }
    h1 { margin: 0 0 16px; font-size: 18px; font-weight: 650; }
    fieldset {
      border: 1px solid #c8d2d6;
      border-radius: 6px;
      margin: 0 0 14px;
      padding: 12px;
    }
    legend { padding: 0 4px; font-size: 13px; font-weight: 650; }
    label { display: grid; gap: 4px; margin: 0 0 10px; font-size: 13px; }
    input, select, button { font: inherit; box-sizing: border-box; }
    input, select {
      width: 100%;
      padding: 7px 8px;
      border: 1px solid #aebbc1;
      border-radius: 5px;
      background: white;
    }
    input[type="range"] { padding: 0; }
    button {
      min-height: 36px;
      border: 1px solid #94a3aa;
      border-radius: 5px;
      background: #ffffff;
      cursor: pointer;
    }
    button.primary { background: #1d4f63; border-color: #1d4f63; color: white; }
    .row, .buttons { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    .wide { grid-column: 1 / -1; }
    .zoom-row { display: grid; grid-template-columns: 1fr 64px; gap: 8px; align-items: center; }
    .status { min-height: 20px; font-size: 13px; color: #4b5f68; white-space: pre-wrap; }
    .variants {
      display: grid;
      grid-template-columns: 1fr;
      gap: 12px;
    }
    .variant {
      border: 2px solid #c8d2d6;
      background: white;
      border-radius: 6px;
      padding: 6px;
      cursor: pointer;
    }
    .variant.selected { border-color: #1d4f63; }
    .variant img {
      display: block;
      width: 100%;
      height: 280px;
      object-fit: contain;
      background: #eef2f3;
    }
    .variant-title {
      margin-bottom: 5px;
      font-size: 12px;
      font-weight: 650;
    }
  </style>
</head>
<body>
  <div class="app">
    <main class="stage">
      <div class="topbar">
        <div><strong id="fileName">-</strong> <span id="counter"></span></div>
        <div class="buttons" style="width: 180px;">
          <button id="prevBtn">前へ</button>
          <button id="nextBtn">次へ</button>
        </div>
      </div>
      <div class="image-wrap">
        <div class="canvas-box">
          <img id="pageImage" alt="">
          <canvas id="canvas"></canvas>
        </div>
      </div>
    </main>
    <aside>
      <h1>候補生成版</h1>

      <fieldset>
        <legend>指定</legend>
        <label>処理
          <select id="tool">
            <option value="white_glow">白ボカシ</option>
            <option value="white_fill">白隠し</option>
            <option value="mosaic">モザイク</option>
          </select>
        </label>
        <div class="row">
          <label>x<input id="x" type="number" step="1"></label>
          <label>y<input id="y" type="number" step="1"></label>
        </div>
        <label>形
          <select id="shape">
            <option value="ellipse">ellipse</option>
            <option value="rect">rect</option>
            <option value="circle">circle</option>
          </select>
        </label>
      </fieldset>

      <fieldset>
        <legend>表示</legend>
        <label>zoom
          <div class="zoom-row">
            <input id="zoom" type="range" min="20" max="120" step="5" value="60">
            <input id="zoomValue" type="number" min="20" max="120" step="5" value="60">
          </div>
        </label>
        <div class="buttons">
          <button id="fitHeightBtn">高さに合わせる</button>
          <button id="actualSizeBtn">100%</button>
        </div>
      </fieldset>

      <fieldset>
        <legend>操作</legend>
        <div class="buttons">
          <button id="variantsBtn" class="primary wide">候補生成</button>
          <button id="acceptBtn" class="primary">選択を採用</button>
          <button id="clearBtn">Clear</button>
        </div>
        <div class="status" id="status"></div>
      </fieldset>

      <fieldset>
        <legend>候補</legend>
        <div id="variants" class="variants"></div>
      </fieldset>
    </aside>
  </div>

  <script>
    const state = {
      images: [],
      index: 0,
      variants: [],
      selected: null
    };

    const el = id => document.getElementById(id);
    const pageImage = el("pageImage");
    const canvas = el("canvas");
    const ctx = canvas.getContext("2d");

    function currentName() { return state.images[state.index] || ""; }
    function num(id) { return Number(el(id).value || 0); }
    function setStatus(text) { el("status").textContent = text; }
    function zoomRatio() { return Math.max(Number(el("zoom").value || 100), 1) / 100; }

    function baseOperation() {
      return {
        tool: el("tool").value,
        shape: el("shape").value,
        x: num("x"),
        y: num("y")
      };
    }

    function drawShape(op, color) {
      ctx.save();
      ctx.translate(op.x, op.y);
      ctx.rotate((op.angle || 0) * Math.PI / 180);
      ctx.strokeStyle = color;
      ctx.lineWidth = 3;
      ctx.setLineDash([9, 5]);
      if (op.shape === "rect") {
        ctx.strokeRect(-op.width / 2, -op.height / 2, op.width, op.height);
      } else {
        ctx.beginPath();
        const rx = op.shape === "circle" ? Math.max(op.width, op.height) / 2 : op.width / 2;
        const ry = op.shape === "circle" ? Math.max(op.width, op.height) / 2 : op.height / 2;
        ctx.ellipse(0, 0, rx, ry, 0, 0, Math.PI * 2);
        ctx.stroke();
      }
      ctx.restore();
    }

    function drawGuide() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      if (state.selected !== null && state.variants[state.selected]) {
        drawShape(state.variants[state.selected].operation, "rgba(230, 40, 40, 0.85)");
      } else if (el("x").value && el("y").value) {
        drawShape({...baseOperation(), width: 180, height: 90, angle: 0}, "rgba(20, 90, 190, 0.9)");
      }
    }

    function applyZoom() {
      const ratio = zoomRatio();
      const width = Math.round(pageImage.naturalWidth * ratio);
      const height = Math.round(pageImage.naturalHeight * ratio);
      pageImage.style.width = width + "px";
      pageImage.style.height = height + "px";
      canvas.style.width = width + "px";
      canvas.style.height = height + "px";
      el("zoomValue").value = el("zoom").value;
      drawGuide();
    }

    function fitCanvas() {
      canvas.width = pageImage.naturalWidth;
      canvas.height = pageImage.naturalHeight;
      applyZoom();
    }

    function renderVariants() {
      const container = el("variants");
      container.innerHTML = "";
      state.variants.forEach((variant, index) => {
        const card = document.createElement("div");
        card.className = "variant" + (state.selected === index ? " selected" : "");
        card.addEventListener("click", () => {
          state.selected = index;
          renderVariants();
          drawGuide();
        });
        const title = document.createElement("div");
        title.className = "variant-title";
        title.textContent = `${index + 1}. ${variant.name}`;
        const img = document.createElement("img");
        img.src = variant.preview_url;
        img.title = "クリックで別タブ表示";
        img.addEventListener("click", event => {
          event.stopPropagation();
          window.open(variant.preview_url, "_blank");
        });
        card.appendChild(title);
        card.appendChild(img);
        container.appendChild(card);
      });
    }

    async function loadImages() {
      const response = await fetch("/api/images");
      const data = await response.json();
      state.images = data.images;
      state.index = 0;
      await loadCurrent();
    }

    async function loadCurrent() {
      const name = currentName();
      el("fileName").textContent = name || "-";
      el("counter").textContent = name ? `${state.index + 1} / ${state.images.length}` : "";
      state.variants = [];
      state.selected = null;
      renderVariants();
      if (!name) return;
      pageImage.src = `/image?name=${encodeURIComponent(name)}&t=${Date.now()}`;
      setStatus("クリックして地点を指定");
    }

    canvas.addEventListener("click", event => {
      const rect = canvas.getBoundingClientRect();
      const scaleX = canvas.width / rect.width;
      const scaleY = canvas.height / rect.height;
      el("x").value = Math.round((event.clientX - rect.left) * scaleX);
      el("y").value = Math.round((event.clientY - rect.top) * scaleY);
      state.variants = [];
      state.selected = null;
      renderVariants();
      drawGuide();
    });

    pageImage.addEventListener("load", fitCanvas);
    for (const id of ["tool", "shape", "x", "y"]) el(id).addEventListener("input", drawGuide);
    el("zoom").addEventListener("input", applyZoom);
    el("zoomValue").addEventListener("change", () => {
      const value = Math.min(Math.max(Number(el("zoomValue").value || 60), 20), 120);
      el("zoom").value = value;
      applyZoom();
    });
    el("fitHeightBtn").addEventListener("click", () => {
      const wrap = document.querySelector(".image-wrap");
      const value = Math.floor((Math.max(wrap.clientHeight - 32, 100) / pageImage.naturalHeight) * 100);
      el("zoom").value = Math.min(Math.max(value, 20), 120);
      applyZoom();
    });
    el("actualSizeBtn").addEventListener("click", () => {
      el("zoom").value = 100;
      applyZoom();
    });

    el("variantsBtn").addEventListener("click", async () => {
      if (!el("x").value || !el("y").value) {
        setStatus("先に画像をクリック");
        return;
      }
      setStatus("候補生成中...");
      const response = await fetch("/api/variants", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({image: currentName(), operation: baseOperation()})
      });
      const data = await response.json();
      if (!response.ok) {
        setStatus(data.error || "候補生成失敗");
        return;
      }
      state.variants = data.variants;
      state.selected = 0;
      renderVariants();
      drawGuide();
      setStatus(`候補: ${state.variants.length}`);
    });

    el("acceptBtn").addEventListener("click", async () => {
      if (state.selected === null || !state.variants[state.selected]) {
        setStatus("先に候補を選択");
        return;
      }
      const response = await fetch("/api/accept", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({image: currentName(), variant: state.variants[state.selected]})
      });
      const data = await response.json();
      if (!response.ok) {
        setStatus(data.error || "採用失敗");
        return;
      }
      setStatus(`採用済み\n${data.overlay}\n${data.preview}`);
    });

    el("clearBtn").addEventListener("click", () => {
      state.variants = [];
      state.selected = null;
      renderVariants();
      drawGuide();
      setStatus("クリア済み");
    });

    el("prevBtn").addEventListener("click", async () => {
      if (state.index > 0) {
        state.index -= 1;
        await loadCurrent();
      }
    });
    el("nextBtn").addEventListener("click", async () => {
      if (state.index + 1 < state.images.length) {
        state.index += 1;
        await loadCurrent();
      }
    });

    window.addEventListener("keydown", event => {
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLSelectElement) return;
      if (event.key === "a") el("tool").value = "white_fill";
      if (event.key === "s") el("tool").value = "white_glow";
      if (event.key === "d") el("tool").value = "mosaic";
      if (/^[1-9]$/.test(event.key)) {
        const index = Number(event.key) - 1;
        if (state.variants[index]) {
          state.selected = index;
          renderVariants();
          drawGuide();
        }
      }
      drawGuide();
    });

    loadImages().catch(error => setStatus(String(error)));
  </script>
</body>
</html>
"""


def variant_operations(base: dict[str, object]) -> list[dict[str, object]]:
    tool = str(base.get("tool", "white_glow"))
    shape = str(base.get("shape", "ellipse"))
    x = int(base["x"])
    y = int(base["y"])

    if tool == "mosaic":
        presets = [
            ("小", 110, 55, 0, 8, 0),
            ("中", 160, 80, 0, 12, 0),
            ("大", 220, 110, 0, 16, 0),
            ("横長 -15", 230, 80, -15, 12, 0),
            ("横長 +15", 230, 80, 15, 12, 0),
            ("広め", 280, 120, 0, 14, 0),
        ]
        return [
            {
                "name": name,
                "tool": tool,
                "shape": shape,
                "x": x,
                "y": y,
                "width": width,
                "height": height,
                "angle": angle,
                "block_size": block_size,
                "feather": feather,
                "opacity": 1.0,
            }
            for name, width, height, angle, block_size, feather in presets
        ]

    if tool == "white_fill":
        presets = [
            ("小", 100, 45, 0, 1, 0),
            ("中", 150, 70, 0, 2, 0),
            ("大", 220, 100, 0, 3, 0),
            ("横長 -15", 230, 70, -15, 2, 0),
            ("横長 +15", 230, 70, 15, 2, 0),
            ("広め", 280, 120, 0, 4, 0),
        ]
        return [
            {
                "name": name,
                "tool": tool,
                "shape": shape,
                "x": x,
                "y": y,
                "width": width,
                "height": height,
                "angle": angle,
                "feather": feather,
                "opacity": 1.0,
            }
            for name, width, height, angle, feather, _ in presets
        ]

    presets = [
        ("小", 90, 40, 0, 28),
        ("中", 130, 60, 0, 42),
        ("大", 185, 85, 0, 58),
        ("横長 -15", 200, 62, -15, 46),
        ("横長 +15", 200, 62, 15, 46),
        ("広め", 250, 105, 0, 68),
    ]
    return [
        {
            "name": name,
            "tool": "white_glow",
            "shape": shape,
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "angle": angle,
            "glow": glow,
            "opacity": 1.0,
        }
        for name, width, height, angle, glow in presets
    ]


class VariantsHandler(BaseHTTPRequestHandler):
    images_dir: Path
    output_dir: Path

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")

    def send_json(self, payload: object, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_bytes(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_bytes(INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
            return
        if parsed.path == "/api/images":
            self.send_json({"images": sorted(image_paths(self.images_dir))})
            return
        if parsed.path == "/image":
            self.handle_image(parsed.query)
            return
        if parsed.path == "/output":
            self.handle_output(parsed.query)
            return
        self.send_json({"error": "not found"}, status=404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/variants":
            self.handle_variants()
            return
        if parsed.path == "/api/accept":
            self.handle_accept()
            return
        self.send_json({"error": "not found"}, status=404)

    def safe_image_path(self, name: str) -> Path:
        paths = image_paths(self.images_dir)
        if name not in paths:
            raise ValueError(f"Unknown image: {name}")
        return paths[name]

    def safe_output_path(self, name: str) -> Path:
        path = (self.output_dir / name).resolve()
        if not str(path).startswith(str(self.output_dir.resolve())):
            raise ValueError("Invalid output path.")
        return path

    def handle_image(self, query: str) -> None:
        try:
            name = parse_qs(query).get("name", [""])[0]
            path = self.safe_image_path(name)
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            self.send_bytes(path.read_bytes(), content_type)
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=400)

    def handle_output(self, query: str) -> None:
        try:
            name = parse_qs(query).get("name", [""])[0]
            path = self.safe_output_path(name)
            if path.suffix.lower() not in IMAGE_EXTENSIONS | {".json"}:
                raise ValueError("Unsupported output file.")
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            self.send_bytes(path.read_bytes(), content_type)
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=400)

    def handle_variants(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            image_name = payload["image"]
            image_path = self.safe_image_path(image_name)
            operations = variant_operations(payload["operation"])
            stamp = int(time.time() * 1000)
            variant_root = self.output_dir / "variants" / f"{Path(image_name).stem}_{stamp}"

            variants = []
            for index, operation in enumerate(operations, start=1):
                variant_dir = variant_root / f"v{index:02d}"
                variant_dir.mkdir(parents=True, exist_ok=True)
                ops_path = variant_dir / "ops_input.json"
                render_operation = {key: value for key, value in operation.items() if key != "name"}
                with ops_path.open("w", encoding="utf-8") as file:
                    json.dump({"operations": [render_operation]}, file, ensure_ascii=False, indent=2)
                overlay_path, preview_path, log_path = create_overlay(image_path, ops_path, variant_dir)
                preview_rel = preview_path.relative_to(self.output_dir).as_posix()
                overlay_rel = overlay_path.relative_to(self.output_dir).as_posix()
                log_rel = log_path.relative_to(self.output_dir).as_posix()
                variants.append(
                    {
                        "name": operation["name"],
                        "operation": render_operation,
                        "preview": str(preview_path),
                        "overlay": str(overlay_path),
                        "log": str(log_path),
                        "preview_rel": preview_rel,
                        "overlay_rel": overlay_rel,
                        "log_rel": log_rel,
                        "preview_url": f"/output?name={quote(preview_rel)}&t={stamp}",
                    }
                )

            self.send_json({"variants": variants})
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=400)

    def handle_accept(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            image_name = payload["image"]
            self.safe_image_path(image_name)
            variant = payload["variant"]

            overlay_src = self.safe_output_path(variant["overlay_rel"])
            preview_src = self.safe_output_path(variant["preview_rel"])
            log_src = self.safe_output_path(variant["log_rel"])
            self.output_dir.mkdir(parents=True, exist_ok=True)
            stem = Path(image_name).stem
            overlay_dst = self.output_dir / f"{stem}_alpha.png"
            preview_dst = self.output_dir / f"{stem}_preview.jpg"
            log_dst = self.output_dir / f"{stem}_ops.json"
            shutil.copyfile(overlay_src, overlay_dst)
            shutil.copyfile(preview_src, preview_dst)
            shutil.copyfile(log_src, log_dst)
            self.send_json({"overlay": str(overlay_dst), "preview": str(preview_dst), "log": str(log_dst)})
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=400)


def run_server(images_dir: Path, output_dir: Path, host: str, port: int) -> None:
    class ConfiguredHandler(VariantsHandler):
        pass

    ConfiguredHandler.images_dir = images_dir
    ConfiguredHandler.output_dir = output_dir

    server = ThreadingHTTPServer((host, port), ConfiguredHandler)
    print(f"images: {images_dir}")
    print(f"output: {output_dir}")
    print(f"url: http://{host}:{port}")
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Start a browser UI that generates correction variants.")
    parser.add_argument("--images", type=Path, default=DEFAULT_IMAGES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    run_server(args.images, args.output, args.host, args.port)


if __name__ == "__main__":
    main()
