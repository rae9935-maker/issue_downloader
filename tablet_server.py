#!/usr/bin/env python3
"""안드로이드 태블릿 브라우저에서 보고서를 받고 합친다.

Termux에서 이 파일을 실행한 뒤, Chrome으로 http://127.0.0.1:8765 를 연다.
받기·합치기 동작은 download_merge.py와 같다.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from download_merge import download_dir_for, fetch_categories, run_one, safe_filename

HOST = "127.0.0.1"
PORT = 8765
MAX_BATCH = 400
PROGRESS = re.compile(r"^\[(\d+)/(\d+)\]")
CODE = re.compile(r"[A-Za-z0-9]+")

PAGE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#f3f0e8">
<title>국회입법조사처 받기</title>
<style>
  :root {
    --ink: #1c241f;
    --muted: #5d675f;
    --paper: #f3f0e8;
    --card: #fffdf8;
    --line: #ddd4c4;
    --accent: #0c6b4d;
    --accent-press: #084e38;
    --warn: #8a4b08;
    --bar: #e7e1d4;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: system-ui, "Apple SD Gothic Neo", "Noto Sans KR", sans-serif;
    background: var(--paper);
    color: var(--ink);
    font-size: 18px;
    line-height: 1.45;
  }
  header, main { padding: 20px 20px 8px; max-width: 1080px; margin: 0 auto; }
  h1 { font-size: 1.7rem; line-height: 1.25; margin: 0 0 8px; }
  h2 { font-size: 1.05rem; margin: 0 0 10px; }
  p { margin: 0 0 12px; }
  .lede, .hint, .place { color: var(--muted); }
  .panel {
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 16px;
    padding: 16px;
    margin-bottom: 16px;
  }
  label { display: block; font-weight: 650; margin: 12px 0; }
  input, select {
    display: block;
    width: 100%;
    min-height: 48px;
    margin-top: 6px;
    padding: 8px 12px;
    font: inherit;
    color: inherit;
    background: #fff;
    border: 1px solid var(--line);
    border-radius: 12px;
  }
  button { font: inherit; }
  .chips { display: flex; flex-wrap: wrap; gap: 8px; }
  .chip {
    min-height: 48px;
    padding: 10px 16px;
    border-radius: 999px;
    border: 1px solid var(--line);
    background: #fff;
    color: var(--ink);
  }
  .chip[aria-pressed="true"] {
    background: var(--accent);
    border-color: var(--accent);
    color: #fff;
  }
  .range { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .count { font-size: 1.35rem; font-weight: 750; margin: 4px 0 12px; }
  .count.warn { color: var(--warn); }
  .primary, .file-link {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 56px;
    width: 100%;
    border: 0;
    border-radius: 14px;
    background: var(--accent);
    color: #fff;
    font-weight: 750;
    text-decoration: none;
    text-align: center;
  }
  .primary:disabled { background: #9aa79f; }
  .primary:active, .chip[aria-pressed="true"]:active { background: var(--accent-press); }
  .bar {
    height: 14px;
    background: var(--bar);
    border-radius: 999px;
    overflow: hidden;
    margin-bottom: 8px;
  }
  #bar { height: 100%; width: 0; background: var(--accent); }
  #log {
    max-height: 220px;
    overflow: auto;
    margin: 8px 0 0;
    padding-left: 1.2rem;
    font-size: 0.92rem;
  }
  #files { list-style: none; padding: 0; margin: 0; }
  #files li { margin: 0 0 10px; }
  .file-link { min-height: 48px; background: #fff; color: var(--ink); border: 1px solid var(--line); }
  .error { color: var(--warn); font-weight: 700; }
  @media (min-width: 900px) {
    .columns { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
    .columns .panel { margin-bottom: 0; }
  }
</style>
</head>
<body>
<header>
  <h1>태블릿에서 보고서 받기</h1>
  <p class="lede">주제를 누르고 시작·끝 번호를 넣은 뒤 받습니다. 개수는 끝에서 시작을 뺀 수에 1을 더한 값입니다. 이미 받은 문서는 건너뜁니다.</p>
  <p class="place" id="place"></p>
</header>
<main>
  <section class="panel">
    <h2>목록과 주제</h2>
    <label>목록
      <select id="cms">
        <option value="CM0018">이슈와논점</option>
        <option value="CM0043">연구보고서</option>
      </select>
    </label>
    <div id="categories" class="chips" role="group" aria-label="주제"></div>
    <p class="hint" id="library"></p>
  </section>
  <div class="columns">
    <section class="panel">
      <h2>구간</h2>
      <div class="range">
        <label>시작 번호
          <input id="start" type="number" min="1" step="1" inputmode="numeric" value="1">
        </label>
        <label>끝 번호
          <input id="end" type="number" min="1" step="1" inputmode="numeric" value="50">
        </label>
      </div>
      <p class="count" id="count">50개</p>
      <label>제목 검색, 비워 두어도 됩니다
        <input id="keyword" type="search" maxlength="80" autocomplete="off">
      </label>
      <button class="primary" id="go" type="button">이 구간 받기</button>
      <p class="hint">50개씩 나누면 태블릿이 덜 멈춥니다. 한 구간이 끝나면 다음 번호로 넘어갑니다. 받는 동안 화면을 켜 두세요.</p>
    </section>
    <section class="panel">
      <h2>진행</h2>
      <div class="bar" aria-hidden="true"><div id="bar"></div></div>
      <p id="status" aria-live="polite">대기 중</p>
      <p class="error" id="error" hidden></p>
      <ol id="log"></ol>
      <p id="result" hidden><a class="primary" id="open" href="#" target="_blank" rel="noopener">합친 PDF 열기</a></p>
    </section>
  </div>
  <section class="panel">
    <h2>받아 둔 PDF</h2>
    <ul id="files"></ul>
    <p class="hint" id="files-empty">아직 없습니다.</p>
  </section>
</main>
<script>
const cms = document.querySelector("#cms");
const categories = document.querySelector("#categories");
const library = document.querySelector("#library");
const start = document.querySelector("#start");
const end = document.querySelector("#end");
const keyword = document.querySelector("#keyword");
const count = document.querySelector("#count");
const go = document.querySelector("#go");
const status = document.querySelector("#status");
const errorBox = document.querySelector("#error");
const log = document.querySelector("#log");
const bar = document.querySelector("#bar");
const result = document.querySelector("#result");
const openLink = document.querySelector("#open");
const files = document.querySelector("#files");
const filesEmpty = document.querySelector("#files-empty");
const place = document.querySelector("#place");

let selectedId = "";
let items = [];
let polling = false;
let wasRunning = false;

function batchSize() {
  const s = Number(start.value);
  const e = Number(end.value);
  if (!Number.isInteger(s) || !Number.isInteger(e) || s < 1 || e < s) return null;
  return e - s + 1;
}

function updateCount() {
  const size = batchSize();
  if (size === null) {
    count.textContent = "시작은 1 이상, 끝은 시작 이상이어야 합니다.";
    count.classList.add("warn");
    return;
  }
  count.textContent = size + "개";
  count.classList.toggle("warn", size > 80);
  if (size > 80) count.textContent = size + "개. 50개씩 나누면 더 안정적입니다.";
}

function renderCategories() {
  categories.replaceChildren();
  if (!items.length) {
    const empty = document.createElement("p");
    empty.className = "hint";
    empty.textContent = "주제를 불러오지 못했습니다. 네트워크를 확인한 뒤 목록을 다시 고르세요.";
    categories.appendChild(empty);
    return;
  }
  for (const item of items) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "chip";
    button.textContent = item.name + " (" + item.id + ")";
    button.setAttribute("aria-pressed", item.id === selectedId ? "true" : "false");
    button.addEventListener("click", () => {
      selectedId = item.id;
      renderCategories();
      loadLibrary();
    });
    categories.appendChild(button);
  }
}

async function loadCategories() {
  categories.textContent = "주제를 불러오는 중";
  try {
    const res = await fetch("/api/categories?cms=" + encodeURIComponent(cms.value));
    const data = await res.json();
    if (!res.ok) {
      items = [];
      renderCategories();
      status.textContent = data.error || "주제를 불러오지 못했습니다.";
      return;
    }
    items = data.categories;
    if (!items.some((item) => item.id === selectedId)) selectedId = "";
    renderCategories();
    loadLibrary();
  } catch (err) {
    items = [];
    renderCategories();
    status.textContent = "주제를 불러오지 못했습니다. 네트워크를 확인하세요.";
  }
}

async function loadLibrary() {
  if (!selectedId) {
    library.textContent = "주제를 고르면 이미 받아 둔 개수를 보여 줍니다.";
    return;
  }
  const res = await fetch("/api/library?categoryId=" + encodeURIComponent(selectedId));
  const data = await res.json();
  const name = items.find((item) => item.id === selectedId);
  library.textContent = (name ? name.name : selectedId) + "에 이미 받아 둔 파일 " + data.count + "개";
}

function applyStatus(data) {
  const total = data.total || 0;
  const done = data.done || 0;
  bar.style.width = total ? Math.min(100, Math.round(done * 100 / total)) + "%" : "0";
  log.replaceChildren();
  for (const line of data.lines || []) {
    const item = document.createElement("li");
    item.textContent = line;
    log.appendChild(item);
  }
  if (log.lastElementChild) log.lastElementChild.scrollIntoView({block: "nearest"});
  errorBox.hidden = !data.error;
  errorBox.textContent = data.error || "";
  if (data.running) {
    status.textContent = total ? done + " / " + total : "목록을 모으는 중";
  } else if (data.summary) {
    status.textContent = data.summary;
  } else if (data.phase === "error") {
    status.textContent = "받지 못했습니다.";
  } else {
    status.textContent = "대기 중";
  }
  if (data.pdf) {
    result.hidden = false;
    openLink.href = "/api/pdf/" + encodeURIComponent(data.pdf);
  } else {
    result.hidden = true;
  }
  go.disabled = Boolean(data.running);
}

async function poll() {
  if (polling) return;
  polling = true;
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    applyStatus(data);
    if (wasRunning && !data.running && data.phase === "done") {
      const size = batchSize();
      if (size) {
        const next = Number(end.value) + 1;
        start.value = String(next);
        end.value = String(next + size - 1);
        updateCount();
      }
      loadFiles();
      loadLibrary();
    }
    wasRunning = Boolean(data.running);
    if (data.running) setTimeout(poll, 700);
  } finally {
    polling = false;
  }
}

async function loadFiles() {
  const res = await fetch("/api/pdfs");
  const data = await res.json();
  files.replaceChildren();
  filesEmpty.hidden = data.pdfs.length > 0;
  for (const file of data.pdfs) {
    const li = document.createElement("li");
    const link = document.createElement("a");
    link.className = "file-link";
    link.target = "_blank";
    link.rel = "noopener";
    link.href = "/api/pdf/" + encodeURIComponent(file.name);
    const mb = (file.size / (1024 * 1024)).toFixed(1);
    link.textContent = file.name + " (" + mb + "MB)";
    li.appendChild(link);
    files.appendChild(li);
  }
}

async function startJob() {
  updateCount();
  if (!selectedId) {
    status.textContent = "주제를 먼저 고르세요.";
    return;
  }
  const size = batchSize();
  if (size === null) {
    status.textContent = "시작 번호와 끝 번호를 확인하세요.";
    return;
  }
  go.disabled = true;
  const res = await fetch("/api/jobs", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      cmsCode: cms.value,
      categoryId: selectedId,
      start: Number(start.value),
      end: Number(end.value),
      keyword: keyword.value.trim()
    })
  });
  const data = await res.json();
  if (!res.ok) {
    go.disabled = false;
    status.textContent = data.error || "시작하지 못했습니다.";
    return;
  }
  wasRunning = true;
  applyStatus(data);
  poll();
}

cms.addEventListener("change", () => {
  selectedId = "";
  loadCategories();
});
start.addEventListener("input", updateCount);
end.addEventListener("input", updateCount);
go.addEventListener("click", startJob);
updateCount();
fetch("/api/info").then((res) => res.json()).then((data) => {
  place.textContent = "PDF 저장 위치: " + data.place;
});
loadCategories();
loadFiles();
poll();
</script>
</body>
</html>
"""


def resolve_dirs(
    download_dir: Path | None,
    output_dir: Path | None,
) -> tuple[Path, Path, str]:
    """Termux 공유 저장소가 있으면 태블릿의 Download/nars 아래에 저장한다."""
    if download_dir is not None or output_dir is not None:
        files = download_dir or Path("downloads")
        pdfs = output_dir or Path("output")
        return files, pdfs, f"{pdfs.resolve()}"
    shared = Path.home() / "storage" / "downloads"
    if shared.is_dir():
        root = shared / "nars"
        return root / "files", root / "pdf", "내 파일 앱의 Download/nars/pdf"
    return Path("downloads"), Path("output"), str(Path("output").resolve())


class App:
    def __init__(self, download_dir: Path, output_dir: Path, place: str):
        self.download_dir = download_dir
        self.output_dir = output_dir
        self.place = place
        self.lock = threading.Lock()
        self.catalog: dict[str, list[tuple[str, str]]] = {}
        self.state = self._idle()

    @staticmethod
    def _idle() -> dict:
        return {
            "running": False,
            "phase": "idle",
            "done": 0,
            "total": 0,
            "lines": [],
            "summary": "",
            "pdf": "",
            "error": "",
        }

    def public_state(self) -> dict:
        with self.lock:
            data = dict(self.state)
            data["lines"] = list(self.state["lines"][-40:])
        return data

    def categories(self, cms_code: str, refresh: bool = False) -> list[tuple[str, str]]:
        if not CODE.fullmatch(cms_code):
            raise ValueError("목록 코드가 올바르지 않습니다.")
        if not refresh:
            with self.lock:
                cached = self.catalog.get(cms_code)
            if cached is not None:
                return cached
        found = fetch_categories(cms_code)
        with self.lock:
            self.catalog[cms_code] = found
        return found

    def library_count(self, category_id: str) -> int:
        if not CODE.fullmatch(category_id):
            raise ValueError("주제를 고르세요.")
        path = download_dir_for(self.download_dir, category_id) / "manifest.json"
        if not path.is_file():
            return 0
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            return 0
        return len(loaded)

    def list_pdfs(self) -> list[dict]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        found = []
        for path in self.output_dir.glob("*.pdf"):
            if not path.is_file():
                continue
            stat = path.stat()
            found.append({"name": path.name, "size": stat.st_size, "mtime": stat.st_mtime})
        found.sort(key=lambda item: item["mtime"], reverse=True)
        return found

    def resolve_pdf(self, name: str) -> Path | None:
        if not name or name != Path(name).name or not name.lower().endswith(".pdf"):
            return None
        root = self.output_dir.resolve()
        candidate = (root / name).resolve()
        if not candidate.is_relative_to(root) or not candidate.is_file():
            return None
        return candidate

    def note(self, line: str) -> None:
        match = PROGRESS.match(line)
        with self.lock:
            self.state["lines"].append(line)
            if len(self.state["lines"]) > 200:
                self.state["lines"] = self.state["lines"][-200:]
            if match:
                self.state["done"] = int(match.group(1))
                self.state["total"] = int(match.group(2))
                self.state["phase"] = "download"
            if line.startswith("완료:") and "->" in line:
                self.state["summary"] = line
                tail = line.split("->", 1)[1]
                pdf_name = Path(tail.split("(", 1)[0].strip()).name
                if pdf_name.lower().endswith(".pdf"):
                    self.state["pdf"] = pdf_name

    def start_job(self, payload: dict) -> tuple[int, dict]:
        with self.lock:
            if self.state["running"]:
                return 409, {"error": "이미 받는 중입니다. 이 구간이 끝난 뒤에 다음 구간을 누르세요."}
        try:
            cms_code = str(payload.get("cmsCode") or "CM0018").strip()
            category_id = str(payload.get("categoryId") or "").strip()
            keyword = str(payload.get("keyword") or "").strip()
            start = int(payload["start"])
            end = int(payload["end"])
        except (KeyError, TypeError, ValueError):
            return 400, {"error": "주제, 시작 번호, 끝 번호가 필요합니다."}
        if not CODE.fullmatch(cms_code):
            return 400, {"error": "목록 코드가 올바르지 않습니다."}
        if not CODE.fullmatch(category_id):
            return 400, {"error": "주제를 고르세요."}
        if start < 1 or end < start:
            return 400, {"error": "시작 번호는 1 이상이고, 끝 번호는 시작 번호 이상이어야 합니다."}
        count = end - start + 1
        if count > MAX_BATCH:
            return 400, {
                "error": (
                    f"한 번에 {MAX_BATCH}개까지 받을 수 있습니다. "
                    f"이번 요청은 {count}개라서 구간을 나눠 주세요."
                )
            }
        if len(keyword) > 80:
            return 400, {"error": "검색어가 너무 깁니다."}
        try:
            catalog = dict(self.categories(cms_code))
        except ValueError as exc:
            return 400, {"error": str(exc)}
        except RuntimeError as exc:
            return 502, {"error": str(exc)}
        if category_id not in catalog:
            return 400, {"error": "목록에 없는 주제입니다. 주제를 다시 고르세요."}
        category_name = catalog[category_id]
        self.output_dir.mkdir(parents=True, exist_ok=True)
        output = self.output_dir / (
            f"{category_id}_{safe_filename(category_name)}_{start:04d}-{end:04d}.pdf"
        )
        params = {
            "cms_code": cms_code,
            "keyword": keyword,
            "search_type": "TITLE",
            "category_id": category_id,
            "category_name": category_name,
            "start_index": start,
            "end_index": end,
            "output_spec": output,
            "target_count": 1,
            "download_dir": download_dir_for(self.download_dir, category_id),
            "workers": 2,
            "log": self.note,
        }
        with self.lock:
            if self.state["running"]:
                return 409, {"error": "이미 받는 중입니다. 이 구간이 끝난 뒤에 다음 구간을 누르세요."}
            self.state = {
                "running": True,
                "phase": "list",
                "done": 0,
                "total": count,
                "lines": [f"{category_name} {start}–{end}번째, {count}개를 받습니다."],
                "summary": "",
                "pdf": "",
                "error": "",
            }
        threading.Thread(target=self._run_job, args=(params,), daemon=True).start()
        return 202, self.public_state()

    def _run_job(self, params: dict) -> None:
        try:
            code = run_one(**params)
        except Exception as exc:
            with self.lock:
                self.state["running"] = False
                self.state["phase"] = "error"
                self.state["error"] = str(exc)
                self.state["lines"].append(str(exc))
            return
        with self.lock:
            self.state["running"] = False
            if code == 0:
                self.state["phase"] = "done"
                self.state["done"] = self.state["total"] or self.state["done"]
            else:
                self.state["phase"] = "error"
                if not self.state["error"]:
                    self.state["error"] = (
                        "일부 문서를 받지 못했습니다. 같은 구간을 다시 누르면 이미 받은 파일은 건너뜁니다."
                    )


def handler_for(app: App):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args) -> None:
            return

        def do_GET(self) -> None:
            self._route("GET")

        def do_POST(self) -> None:
            self._route("POST")

        def _route(self, method: str) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            try:
                if method == "GET" and path == "/":
                    self._bytes(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
                elif method == "GET" and path == "/api/info":
                    self._json(200, {"place": app.place})
                elif method == "GET" and path == "/api/status":
                    self._json(200, app.public_state())
                elif method == "GET" and path == "/api/categories":
                    self._categories(parse_qs(parsed.query))
                elif method == "GET" and path == "/api/library":
                    self._library(parse_qs(parsed.query))
                elif method == "GET" and path == "/api/pdfs":
                    self._json(200, {"pdfs": app.list_pdfs()})
                elif method == "GET" and path.startswith("/api/pdf/"):
                    self._pdf(unquote(path.removeprefix("/api/pdf/")))
                elif method == "POST" and path == "/api/jobs":
                    self._job()
                else:
                    self._json(404, {"error": "없는 주소입니다."})
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            except RuntimeError as exc:
                self._json(502, {"error": str(exc)})

        def _categories(self, query: dict[str, list[str]]) -> None:
            cms_code = query.get("cms", ["CM0018"])[0]
            refresh = query.get("refresh", ["0"])[0] == "1"
            rows = app.categories(cms_code, refresh=refresh)
            self._json(200, {"categories": [{"id": cid, "name": name} for cid, name in rows]})

        def _library(self, query: dict[str, list[str]]) -> None:
            category_id = query.get("categoryId", [""])[0]
            self._json(200, {"count": app.library_count(category_id)})

        def _pdf(self, name: str) -> None:
            path = app.resolve_pdf(name)
            if path is None:
                self._json(404, {"error": "PDF가 없습니다."})
                return
            size = path.stat().st_size
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "no-store")
            encoded = quote(path.name)
            self.send_header(
                "Content-Disposition",
                f"inline; filename=\"report.pdf\"; filename*=UTF-8''{encoded}",
            )
            self.end_headers()
            with path.open("rb") as handle:
                while True:
                    chunk = handle.read(64 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)

        def _job(self) -> None:
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length < 0 or length > 8000:
                self._json(413, {"error": "요청이 너무 큽니다."})
                return
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError):
                self._json(400, {"error": "요청 형식이 올바르지 않습니다."})
                return
            if not isinstance(payload, dict):
                self._json(400, {"error": "요청 형식이 올바르지 않습니다."})
                return
            status, body = app.start_job(payload)
            self._json(status, body)

        def _json(self, status: int, payload: dict) -> None:
            self._bytes(
                status,
                json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                "application/json; charset=utf-8",
            )

        def _bytes(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    return Handler


def hold_wake_lock() -> bool:
    binary = shutil.which("termux-wake-lock")
    if not binary:
        return False
    subprocess.run([binary], check=False)
    return True


def release_wake_lock() -> None:
    binary = shutil.which("termux-wake-unlock")
    if binary:
        subprocess.run([binary], check=False)


def main() -> int:
    parser = argparse.ArgumentParser(description="태블릿 브라우저에서 국회입법조사처 보고서를 받습니다.")
    parser.add_argument("--host", default=HOST, help="기본값은 이 태블릿만 접속하는 127.0.0.1 입니다.")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--download-dir", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    download_dir, output_dir, place = resolve_dirs(args.download_dir, args.output_dir)
    app = App(download_dir, output_dir, place)
    server = ThreadingHTTPServer((args.host, args.port), handler_for(app))
    url = f"http://127.0.0.1:{args.port}"
    print(f"태블릿 Chrome에서 이 주소를 여세요: {url}")
    print(f"PDF 저장 위치: {place}")
    held = hold_wake_lock()
    if held:
        print("화면이 꺼져도 받기가 이어지도록 깨우기를 유지합니다.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n종료합니다.")
    finally:
        server.server_close()
        if held:
            release_wake_lock()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
