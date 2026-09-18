from __future__ import annotations

import argparse
import json
import mimetypes
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from compare_modified_regions import IMAGE_EXTENSIONS, ROOT_DIR, image_paths
from create_overlay import create_overlay


DEFAULT_IMAGES = ROOT_DIR / "tests" / "B_original" / "image"
DEFAULT_OUTPUT = ROOT_DIR / "output" / "manual_overlay"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000


INDEX_HTML = r"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Manual Overlay PoC</title>
  <style>
    :root {
      color-scheme: light;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #eef2f3;
      color: #1e2930;
    }
    body {
      margin: 0;
      height: 100vh;
      overflow: hidden;
    }
    .app {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 320px;
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
      overflow-x: auto;
      overflow-y: scroll;
      scrollbar-gutter: stable;
      background: #d8e0e2;
      border: 1px solid #8b9aa2;
      display: block;
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
    #pageImage {
      display: block;
      max-width: none;
      user-select: none;
    }
    #canvas {
      position: absolute;
      inset: 0;
      cursor: crosshair;
    }
    aside {
      border-left: 1px solid #8b9aa2;
      background: #f8fafb;
      padding: 16px;
      overflow: auto;
    }
    h1 {
      margin: 0 0 16px;
      font-size: 18px;
      font-weight: 650;
    }
    fieldset {
      border: 1px solid #c8d2d6;
      border-radius: 6px;
      margin: 0 0 14px;
      padding: 12px;
    }
    legend {
      padding: 0 4px;
      font-size: 13px;
      font-weight: 650;
    }
    label {
      display: grid;
      gap: 4px;
      margin: 0 0 10px;
      font-size: 13px;
    }
    input, select, button {
      font: inherit;
      box-sizing: border-box;
    }
    input, select {
      width: 100%;
      padding: 7px 8px;
      border: 1px solid #aebbc1;
      border-radius: 5px;
      background: white;
    }
    .row {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
    }
    .buttons {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
    }
    .wide {
      grid-column: 1 / -1;
    }
    .zoom-row {
      display: grid;
      grid-template-columns: 1fr 64px;
      gap: 8px;
      align-items: center;
    }
    input[type="range"] {
      padding: 0;
    }
    button {
      min-height: 36px;
      border: 1px solid #94a3aa;
      border-radius: 5px;
      background: #ffffff;
      cursor: pointer;
    }
    button.primary {
      background: #1d4f63;
      border-color: #1d4f63;
      color: white;
    }
    button:disabled {
      cursor: not-allowed;
      opacity: 0.55;
    }
    .status {
      min-height: 20px;
      font-size: 13px;
      color: #4b5f68;
      white-space: pre-wrap;
    }
    .preview-link {
      display: inline-block;
      margin-top: 8px;
      font-size: 13px;
    }
    .ops {
      max-height: 140px;
      overflow: auto;
      font-family: Consolas, monospace;
      font-size: 12px;
      background: #eef2f3;
      border: 1px solid #c8d2d6;
      padding: 8px;
      white-space: pre-wrap;
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
        <div class="canvas-box" id="canvasBox">
          <img id="pageImage" alt="">
          <canvas id="canvas"></canvas>
        </div>
      </div>
    </main>
    <aside>
      <h1>Manual Overlay PoC</h1>

      <fieldset>
        <legend>処理</legend>
        <label>処理
          <select id="tool">
            <option value="white_fill">白隠し</option>
            <option value="white_glow">白ボカシ</option>
            <option value="mosaic">モザイク</option>
          </select>
        </label>
        <label>形
          <select id="shape">
            <option value="ellipse">ellipse</option>
            <option value="rect">rect</option>
            <option value="circle">circle</option>
          </select>
        </label>
        <div class="row">
          <label>x<input id="x" type="number" step="1"></label>
          <label>y<input id="y" type="number" step="1"></label>
        </div>
        <div class="row">
          <label>幅<input id="width" type="number" step="1" value="160"></label>
          <label>高さ<input id="height" type="number" step="1" value="70"></label>
        </div>
        <div class="row">
          <label>角度<input id="angle" type="number" step="1" value="0"></label>
          <label>境界ぼかし<input id="feather" type="number" step="1" value="2"></label>
        </div>
        <div class="row">
          <label>光彩の広がり<input id="glow" type="number" step="1" value="60"></label>
          <label>モザイク粗さ<input id="blockSize" type="number" step="1" value="12"></label>
        </div>
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
          <button id="addBtn" class="primary">追加</button>
          <button id="undoBtn">Undo</button>
        </div>
        <a id="previewLink" class="preview-link" href="#" target="_blank" hidden>previewを開く</a>
        <div class="buttons">
          <button id="previewBtn" class="wide">Preview</button>
          <button id="renderBtn" class="primary">生成</button>
          <button id="clearBtn">Clear</button>
        </div>
        <div class="status" id="status"></div>
      </fieldset>

      <fieldset>
        <legend>operations</legend>
        <div id="ops" class="ops">[]</div>
      </fieldset>
    </aside>
  </div>

  <script>
    const state = {
      images: [],
      index: 0,
      naturalWidth: 0,
      naturalHeight: 0,
      operations: []
    };

    const el = id => document.getElementById(id);
    const pageImage = el("pageImage");
    const canvas = el("canvas");
    const ctx = canvas.getContext("2d");

    function currentName() {
      return state.images[state.index] || "";
    }

    function num(id) {
      return Number(el(id).value || 0);
    }

    function zoomRatio() {
      return Math.max(Number(el("zoom").value || 100), 1) / 100;
    }

    function currentOperation() {
      const op = {
        tool: el("tool").value,
        shape: el("shape").value,
        x: num("x"),
        y: num("y"),
        width: Math.max(num("width"), 1),
        height: Math.max(num("height"), 1),
        angle: num("angle"),
        feather: Math.max(num("feather"), 0),
        opacity: 1.0
      };
      if (op.tool === "white_glow") op.glow = Math.max(num("glow"), 1);
      if (op.tool === "mosaic") op.block_size = Math.max(num("blockSize"), 2);
      return op;
    }

    function resetOperationInputs(options = {}) {
      if (!options.keepPoint) {
        el("x").value = "";
        el("y").value = "";
      }
      el("shape").value = "ellipse";
      el("angle").value = 0;
      el("feather").value = 2;
      el("glow").value = 60;
      el("blockSize").value = 12;
      if (el("tool").value === "mosaic") {
        el("width").value = 180;
        el("height").value = 90;
      } else if (el("tool").value === "white_glow") {
        el("width").value = 180;
        el("height").value = 90;
      } else {
        el("width").value = 160;
        el("height").value = 70;
      }
    }

    function setStatus(text) {
      el("status").textContent = text;
    }

    function updateOps() {
      el("ops").textContent = JSON.stringify(state.operations, null, 2);
    }

    function fitCanvas() {
      canvas.width = pageImage.naturalWidth;
      canvas.height = pageImage.naturalHeight;
      applyZoom();
      drawOverlayGuide();
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
      drawOverlayGuide();
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

    function drawOverlayGuide() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      for (const op of state.operations) drawShape(op, "rgba(230, 40, 40, 0.75)");
      if (el("x").value && el("y").value) drawShape(currentOperation(), "rgba(20, 90, 190, 0.9)");
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
      state.operations = [];
      updateOps();
      el("previewLink").hidden = true;
      if (!name) return;
      pageImage.src = `/image?name=${encodeURIComponent(name)}&t=${Date.now()}`;
      setStatus("画像をクリックして座標を指定");
    }

    pageImage.addEventListener("load", fitCanvas);
    canvas.addEventListener("click", event => {
      const rect = canvas.getBoundingClientRect();
      const scaleX = canvas.width / rect.width;
      const scaleY = canvas.height / rect.height;
      el("x").value = Math.round((event.clientX - rect.left) * scaleX);
      el("y").value = Math.round((event.clientY - rect.top) * scaleY);
      drawOverlayGuide();
    });

    for (const id of ["tool", "shape", "x", "y", "width", "height", "angle", "feather", "glow", "blockSize"]) {
      el(id).addEventListener("input", drawOverlayGuide);
    }
    el("tool").addEventListener("change", () => {
      resetOperationInputs({keepPoint: true});
      drawOverlayGuide();
    });

    el("zoom").addEventListener("input", applyZoom);
    el("zoomValue").addEventListener("change", () => {
      const value = Math.min(Math.max(Number(el("zoomValue").value || 60), 20), 120);
      el("zoom").value = value;
      applyZoom();
    });
    el("fitHeightBtn").addEventListener("click", () => {
      const wrap = document.querySelector(".image-wrap");
      const availableHeight = Math.max(wrap.clientHeight - 32, 100);
      const value = Math.floor((availableHeight / pageImage.naturalHeight) * 100);
      el("zoom").value = Math.min(Math.max(value, 20), 120);
      applyZoom();
    });
    el("actualSizeBtn").addEventListener("click", () => {
      el("zoom").value = 100;
      applyZoom();
    });

    el("addBtn").addEventListener("click", () => {
      if (!el("x").value || !el("y").value) {
        setStatus("先に画像をクリック");
        return;
      }
      state.operations.push(currentOperation());
      updateOps();
      resetOperationInputs();
      drawOverlayGuide();
      setStatus(`operation追加: ${state.operations.length}`);
    });

    el("undoBtn").addEventListener("click", () => {
      state.operations.pop();
      updateOps();
      drawOverlayGuide();
    });

    el("clearBtn").addEventListener("click", () => {
      state.operations = [];
      updateOps();
      drawOverlayGuide();
      setStatus("クリア済み");
    });

    async function renderOverlay(mode) {
      const operations = state.operations.length ? state.operations : [currentOperation()];
      if (!operations[0].x || !operations[0].y) {
        setStatus("先に画像をクリック");
        return;
      }
      setStatus(mode === "preview" ? "preview生成中..." : "生成中...");
      const response = await fetch("/api/render", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({image: currentName(), operations})
      });
      const data = await response.json();
      if (!response.ok) {
        setStatus(data.error || "生成失敗");
        return;
      }
      el("previewLink").href = data.compare_url || data.preview_url;
      el("previewLink").hidden = false;
      setStatus(`${mode === "preview" ? "preview保存済み" : "生成済み"}\n${data.overlay}\n${data.preview}`);
    }

    el("previewBtn").addEventListener("click", () => renderOverlay("preview"));
    el("renderBtn").addEventListener("click", () => renderOverlay("render"));

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

    window.addEventListener("keydown", async event => {
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLSelectElement) return;
      if (event.key === "a") el("tool").value = "white_fill";
      if (event.key === "s") el("tool").value = "white_glow";
      if (event.key === "d") el("tool").value = "mosaic";
      if (event.key === "+" || event.key === "=") {
        el("width").value = Math.round(num("width") * 1.1);
        el("height").value = Math.round(num("height") * 1.1);
      }
      if (event.key === "-") {
        el("width").value = Math.round(num("width") / 1.1);
        el("height").value = Math.round(num("height") / 1.1);
      }
      if (event.key === "Enter") el("renderBtn").click();
      drawOverlayGuide();
    });

    loadImages().catch(error => setStatus(String(error)));
  </script>
</body>
</html>
"""


COMPARE_HTML = r"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Preview Compare</title>
  <style>
    body {
      margin: 0;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #eef2f3;
      color: #1e2930;
    }
    header {
      position: sticky;
      top: 0;
      z-index: 2;
      padding: 10px 14px;
      background: #f8fafb;
      border-bottom: 1px solid #b7c3c9;
      font-size: 14px;
    }
    .compare {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
      padding: 12px;
      align-items: start;
    }
    .pane {
      min-width: 0;
      background: #d8e0e2;
      border: 1px solid #9aa9b0;
      overflow: auto;
      max-height: calc(100vh - 58px);
    }
    .pane-title {
      position: sticky;
      top: 0;
      padding: 8px 10px;
      background: #f8fafb;
      border-bottom: 1px solid #b7c3c9;
      font-size: 13px;
      font-weight: 650;
    }
    img {
      display: block;
      max-width: none;
      width: 100%;
      height: auto;
      background: white;
    }
  </style>
</head>
<body>
  <header>元画像 / preview 比較</header>
  <main class="compare">
    <section class="pane">
      <div class="pane-title">元画像</div>
      <img src="__ORIGINAL_URL__" alt="">
    </section>
    <section class="pane">
      <div class="pane-title">preview</div>
      <img src="__PREVIEW_URL__" alt="">
    </section>
  </main>
</body>
</html>
"""


class ManualOverlayHandler(BaseHTTPRequestHandler):
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
            self.handle_images()
            return
        if parsed.path == "/image":
            self.handle_image(parsed.query)
            return
        if parsed.path == "/output":
            self.handle_output(parsed.query)
            return
        if parsed.path == "/compare":
            self.handle_compare(parsed.query)
            return
        self.send_json({"error": "not found"}, status=404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/render":
            self.handle_render()
            return
        self.send_json({"error": "not found"}, status=404)

    def handle_images(self) -> None:
        images = sorted(image_paths(self.images_dir))
        self.send_json({"images": images})

    def safe_image_path(self, name: str) -> Path:
        paths = image_paths(self.images_dir)
        if name not in paths:
            raise ValueError(f"Unknown image: {name}")
        return paths[name]

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
            path = (self.output_dir / name).resolve()
            if not str(path).startswith(str(self.output_dir.resolve())):
                raise ValueError("Invalid output path.")
            if path.suffix.lower() not in IMAGE_EXTENSIONS | {".json"}:
                raise ValueError("Unsupported output file.")
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            self.send_bytes(path.read_bytes(), content_type)
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=400)

    def handle_compare(self, query: str) -> None:
        try:
            params = parse_qs(query)
            image = params.get("image", [""])[0]
            preview = params.get("preview", [""])[0]
            self.safe_image_path(image)
            preview_path = (self.output_dir / preview).resolve()
            if not str(preview_path).startswith(str(self.output_dir.resolve())):
                raise ValueError("Invalid preview path.")
            if preview_path.suffix.lower() not in IMAGE_EXTENSIONS:
                raise ValueError("Unsupported preview file.")
            body = (
                COMPARE_HTML.replace("__ORIGINAL_URL__", f"/image?name={image}")
                .replace("__PREVIEW_URL__", f"/output?name={preview}")
                .encode("utf-8")
            )
            self.send_bytes(body, "text/html; charset=utf-8")
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=400)

    def handle_render(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            image_name = payload["image"]
            operations = payload["operations"]
            image_path = self.safe_image_path(image_name)

            ops_path = self.output_dir / f"{Path(image_name).stem}_ops_input.json"
            self.output_dir.mkdir(parents=True, exist_ok=True)
            with ops_path.open("w", encoding="utf-8") as file:
                json.dump({"operations": operations}, file, ensure_ascii=False, indent=2)

            overlay_path, preview_path, log_path = create_overlay(image_path, ops_path, self.output_dir)
            cache_buster = int(time.time() * 1000)
            self.send_json(
                {
                    "overlay": str(overlay_path),
                    "preview": str(preview_path),
                    "log": str(log_path),
                    "preview_url": f"/output?name={preview_path.name}&t={cache_buster}",
                    "overlay_url": f"/output?name={overlay_path.name}&t={cache_buster}",
                    "compare_url": f"/compare?image={image_name}&preview={preview_path.name}&t={cache_buster}",
                }
            )
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=400)


def run_server(images_dir: Path, output_dir: Path, host: str, port: int) -> None:
    class ConfiguredHandler(ManualOverlayHandler):
        pass

    ConfiguredHandler.images_dir = images_dir
    ConfiguredHandler.output_dir = output_dir

    server = ThreadingHTTPServer((host, port), ConfiguredHandler)
    print(f"images: {images_dir}")
    print(f"output: {output_dir}")
    print(f"url: http://{host}:{port}")
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Start a browser UI for manual overlay correction PoC.")
    parser.add_argument("--images", type=Path, default=DEFAULT_IMAGES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    run_server(args.images, args.output, args.host, args.port)


if __name__ == "__main__":
    main()
