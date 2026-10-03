#!/usr/bin/env python3
"""국회입법조사처 보고서 목록을 받아 하나의 PDF로 합친다.

사이트 목록의 [다운로드]와 같은 주소(fileDownload2.do)를 사용한다.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError

LIST_URL = "https://www.nars.go.kr/report/list.do"
DOWNLOAD_URL = "https://www.nars.go.kr/fileDownload2.do"
USER_AGENT = "nars-issue-downloader/1.0 (personal archive; +https://www.nars.go.kr)"
PAGE_SIZE = 10


@dataclass(frozen=True)
class Report:
    index: int
    seq: str
    title: str
    doc_id: str
    filename: str

    @property
    def bookmark(self) -> str:
        title = re.sub(r"\s+", " ", self.title).strip() or self.filename
        return f"{self.seq}. {title}"[:200]


def fetch(url: str, timeout: int = 60, retries: int = 3) -> bytes:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Referer": "https://www.nars.go.kr/report/list.do",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last_error = exc
            time.sleep(0.8 * attempt)
    raise RuntimeError(f"요청 실패: {url}") from last_error


def parse_categories(page_html: str) -> list[tuple[str, str]]:
    """목록 화면의 주제 선택에서 (categoryId, 이름)을 뽑는다. '주제전체'는 제외한다."""
    cleaned = re.sub(r"<!--.*?-->", "", page_html, flags=re.S)
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for category_id, name in re.findall(
        r"setCategoryId\('([^']+)'\);\">([^<]+)",
        cleaned,
    ):
        category_id = category_id.strip()
        name = re.sub(r"\s+", " ", html.unescape(name)).strip()
        if not category_id or category_id == "all" or category_id in seen:
            continue
        seen.add(category_id)
        found.append((category_id, name))
    return found


def parse_list_page(page_html: str) -> list[tuple[str, str, str, str]]:
    """한 목록 페이지에서 (순번, 제목, doc_id, 파일명)을 순서대로 뽑는다."""
    parts = re.split(r"<li>\s*<div>\s*<span>(\d+)</span>", page_html)
    found: list[tuple[str, str, str, str]] = []
    for i in range(1, len(parts), 2):
        seq = parts[i]
        body = parts[i + 1]
        download = re.search(
            r"fileDownLoad\(\s*'([^']+)'\s*,\s*'(.*?)'\s*\)",
            body,
            re.S,
        )
        if not download:
            continue
        title_match = re.search(r'class="tt">\s*<a[^>]*>(.*?)</a>', body, re.S)
        raw_title = title_match.group(1) if title_match else download.group(2)
        title = html.unescape(re.sub(r"<[^>]+>", "", raw_title))
        title = re.sub(r"\s+", " ", title).strip()
        filename = html.unescape(download.group(2)).strip()
        found.append((seq, title, download.group(1), filename))
    return found


def fetch_list_rows(
    cms_code: str,
    page: int,
    keyword: str,
    search_type: str,
    category_id: str,
) -> list[tuple[str, str, str, str]]:
    query = urllib.parse.urlencode(
        {
            "page": page,
            "cmsCode": cms_code,
            "categoryId": category_id,
            "searchType": search_type,
            "searchKeyword": keyword,
        }
    )
    body = fetch(f"{LIST_URL}?{query}").decode("utf-8", errors="replace")
    return parse_list_page(body)


def collect_reports(
    cms_code: str,
    keyword: str,
    search_type: str,
    category_id: str,
    start_index: int,
    end_index: int,
) -> tuple[list[Report], bool, int]:
    """목록 1번째부터 세어 start_index~end_index(포함)만 돌려준다.

    두 번째 값은 요청한 끝 번호보다 목록이 짧아서 일찍 끝났는지, 세 번째는 확인한 마지막 순번이다.
    """
    reports: list[Report] = []
    position = 0
    page = 1
    while position < end_index:
        rows = fetch_list_rows(cms_code, page, keyword, search_type, category_id)
        if not rows:
            return reports, True, position
        for seq, title, doc_id, filename in rows:
            position += 1
            if start_index <= position <= end_index:
                reports.append(
                    Report(
                        index=position,
                        seq=seq,
                        title=title,
                        doc_id=doc_id,
                        filename=filename,
                    )
                )
            if position >= end_index:
                return reports, False, position
        page += 1
        time.sleep(0.15)
    return reports, False, position


def parse_range(text: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d+)\s*-\s*(\d+)", text.strip())
    if not match:
        raise argparse.ArgumentTypeError("범위는 10-59 형식입니다. 시작과 끝은 목록 순번입니다.")
    start, end = int(match.group(1)), int(match.group(2))
    if start < 1:
        raise argparse.ArgumentTypeError("범위 시작은 1 이상이어야 합니다.")
    if end < start:
        raise argparse.ArgumentTypeError("범위 끝은 시작보다 작을 수 없습니다.")
    return start, end


def safe_filename(name: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\r\n]+', "_", name).strip(" .")
    return cleaned[:140] or "report"


def report_path(download_dir: Path, report: Report) -> Path:
    return download_dir / f"{report.index:04d}_{report.doc_id}_{safe_filename(report.filename)}"


def is_valid_pdf(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size <= 500:
        return False
    with path.open("rb") as handle:
        return handle.read(5) == b"%PDF-"


class DownloadLibrary:
    """doc_id 기준으로 이미 받은 파일을 기록한다. 같은 문서는 다시 받지 않는다."""

    def __init__(self, directory: Path):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.manifest_path = directory / "manifest.json"
        self._lock = threading.Lock()
        self.entries: dict[str, str] = {}
        if self.manifest_path.exists():
            loaded = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                self.entries = {str(key): str(value) for key, value in loaded.items()}

    def find(self, report: Report) -> Path | None:
        with self._lock:
            recorded = self.entries.get(report.doc_id)
        if recorded:
            candidate = self.directory / recorded
            if is_valid_pdf(candidate):
                return candidate
        canonical = report_path(self.directory, report)
        if is_valid_pdf(canonical):
            self.remember(report.doc_id, canonical)
            return canonical
        return None

    def remember(self, doc_id: str, path: Path) -> None:
        with self._lock:
            self.entries[doc_id] = path.name
            payload = json.dumps(self.entries, ensure_ascii=False, indent=2) + "\n"
            self.manifest_path.write_text(payload, encoding="utf-8")


def download_one(
    report: Report,
    library: DownloadLibrary,
) -> tuple[Report, Path | None, str | None, str]:
    existing = library.find(report)
    if existing is not None:
        return report, existing, None, "cached"
    dest = report_path(library.directory, report)
    params = urllib.parse.urlencode(
        {
            "doc_id": report.doc_id,
            "fileName": report.filename,
            "timeStamp": str(int(time.time() * 1000)),
        }
    )
    try:
        data = fetch(f"{DOWNLOAD_URL}?{params}")
    except RuntimeError as exc:
        return report, None, str(exc), "failed"
    if not data.startswith(b"%PDF-"):
        return report, None, f"PDF가 아닌 응답 ({len(data)} bytes)", "failed"
    dest.write_bytes(data)
    library.remember(report.doc_id, dest)
    return report, dest, None, "downloaded"


def download_all(
    reports: list[Report],
    library: DownloadLibrary,
    workers: int,
) -> tuple[list[str], dict[str, Path], int, int]:
    failures: list[str] = []
    paths: dict[str, Path] = {}
    downloaded = 0
    cached = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(download_one, report, library) for report in reports]
        done = 0
        total = len(reports)
        for future in as_completed(futures):
            report, path, error, status = future.result()
            done += 1
            if error or path is None:
                failures.append(f"{report.bookmark}: {error}")
                print(
                    f"[{done}/{total}] #{report.index} 실패 {report.doc_id} {error}",
                    file=sys.stderr,
                )
                continue
            paths[report.doc_id] = path
            if status == "cached":
                cached += 1
                print(f"[{done}/{total}] #{report.index} 이미 받음 {report.bookmark}")
            else:
                downloaded += 1
                print(f"[{done}/{total}] #{report.index} {report.bookmark}")
    return failures, paths, downloaded, cached


def merge_pdfs(
    reports: list[Report],
    paths: dict[str, Path],
    output: Path,
) -> tuple[int, int]:
    writer = PdfWriter()
    merged = 0
    skipped = 0
    for report in reports:
        path = paths.get(report.doc_id)
        if path is None or not path.exists():
            skipped += 1
            continue
        try:
            reader = PdfReader(str(path))
            if reader.is_encrypted:
                reader.decrypt("")
            if not reader.pages:
                skipped += 1
                continue
            start = len(writer.pages)
            for page in reader.pages:
                writer.add_page(page)
            writer.add_outline_item(report.bookmark, start)
            merged += 1
        except (PdfReadError, Exception) as exc:
            skipped += 1
            print(f"병합 제외 {path.name}: {exc}", file=sys.stderr)
    if merged == 0:
        raise RuntimeError("합칠 PDF가 없습니다.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as handle:
        writer.write(handle)
    return merged, len(writer.pages)


def list_page_html(cms_code: str) -> str:
    query = urllib.parse.urlencode(
        {
            "page": 1,
            "cmsCode": cms_code,
            "categoryId": "",
            "searchType": "TITLE",
            "searchKeyword": "",
        }
    )
    return fetch(f"{LIST_URL}?{query}").decode("utf-8", errors="replace")


def fetch_categories(cms_code: str) -> list[tuple[str, str]]:
    categories = parse_categories(list_page_html(cms_code))
    if not categories:
        raise RuntimeError("주제(categoryId) 목록을 찾지 못했습니다.")
    return categories


def requested_category_ids(values: list[str]) -> list[str]:
    ids: list[str] = []
    for value in values:
        for part in value.split(","):
            part = part.strip()
            if part and part not in ids:
                ids.append(part)
    return ids


def output_path_for(
    spec: Path | None,
    category_id: str,
    name: str,
    count: int,
    start_index: int,
    end_index: int,
) -> Path:
    span = f"{start_index:04d}-{end_index:04d}"
    stem = f"{category_id}_{safe_filename(name)}" if category_id else "nars_merged"
    filename = f"{stem}_{span}.pdf"
    if spec is None:
        return Path("output") / filename
    if count == 1:
        return spec
    directory = spec if spec.suffix.lower() != ".pdf" else spec.parent
    return directory / filename


def download_dir_for(base: Path, category_id: str) -> Path:
    if not category_id:
        return base
    return base / category_id


def items_before_page(
    cms_code: str,
    keyword: str,
    search_type: str,
    category_id: str,
    start_page: int,
) -> int:
    if start_page <= 1:
        return 0
    position = 0
    for page in range(1, start_page):
        rows = fetch_list_rows(cms_code, page, keyword, search_type, category_id)
        if not rows:
            break
        position += len(rows)
        time.sleep(0.15)
    return position


def run_one(
    *,
    cms_code: str,
    keyword: str,
    search_type: str,
    category_id: str,
    category_name: str,
    start_index: int,
    end_index: int,
    output_spec: Path | None,
    target_count: int,
    download_dir: Path,
    workers: int,
) -> int:
    label = f"{category_id} {category_name}".strip() or "주제전체"
    print(
        f"목록 수집: {label} cmsCode={cms_code} "
        f"categoryId={category_id or '(전체)'} 구간={start_index}-{end_index}"
    )
    reports, ended_early, last_position = collect_reports(
        cms_code=cms_code,
        keyword=keyword,
        search_type=search_type,
        category_id=category_id,
        start_index=start_index,
        end_index=end_index,
    )
    if not reports:
        if ended_early:
            print(
                f"{label}: 목록은 {last_position}건입니다. {start_index}번째부터는 없습니다.",
                file=sys.stderr,
            )
        else:
            print(f"{label}: 다운로드 가능한 문서를 찾지 못했습니다.", file=sys.stderr)
        return 1
    if ended_early and reports[-1].index < end_index:
        print(
            f"{label}: 목록은 {last_position}건입니다. "
            f"{reports[0].index}-{reports[-1].index}만 받습니다."
        )
    output = output_path_for(
        output_spec,
        category_id,
        category_name,
        target_count,
        reports[0].index,
        reports[-1].index,
    )
    print(
        f"{len(reports)}건 선택 ({reports[0].index}-{reports[-1].index}번째). "
        f"다운로드 시작 (동시 {workers}) -> {download_dir}"
    )
    library = DownloadLibrary(download_dir)
    failures, paths, downloaded, cached = download_all(reports, library, workers)
    merged, pages = merge_pdfs(reports, paths, output)
    size_mb = output.stat().st_size / (1024 * 1024)
    print(
        f"완료: {label} {merged}개 문서, {pages}페이지, {size_mb:.1f}MB -> {output} "
        f"(새로 받음 {downloaded}, 이미 있던 파일 {cached})"
    )
    if failures:
        print(f"{label}: 실패한 다운로드 {len(failures)}건", file=sys.stderr)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="국회입법조사처 보고서를 내려받아 하나의 PDF로 합칩니다. "
        "주제(categoryId)마다 파일을 나눌 수 있습니다."
    )
    parser.add_argument(
        "--cms-code",
        default="CM0018",
        help="목록 코드. CM0018은 이슈와논점 (기본값)",
    )
    parser.add_argument(
        "--category-id",
        action="append",
        default=[],
        metavar="ID",
        help="주제 코드. 반복하거나 쉼표로 여러 개를 줄 수 있습니다. "
        "예: b1(재정금융). 여러 개면 주제마다 PDF를 따로 만듭니다.",
    )
    parser.add_argument(
        "--split-by-category",
        action="store_true",
        help="사이트에 있는 주제를 모두 받아, 주제마다 PDF를 따로 만듭니다.",
    )
    parser.add_argument(
        "--list-categories",
        action="store_true",
        help="주제 코드와 이름을 출력하고 끝냅니다.",
    )
    parser.add_argument(
        "--range",
        type=parse_range,
        help="목록 순번 구간. 10-59는 10번째부터 59번째까지 50개입니다. "
        "이미 받은 문서는 다시 받지 않으므로, 다음에는 60-109처럼 이어 가면 됩니다. "
        "이 옵션이 있으면 --limit은 쓰지 않습니다.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="앞에서부터 받을 문서 수 (기본값 100). --range가 있으면 무시됩니다.",
    )
    parser.add_argument(
        "--start-page",
        type=int,
        default=1,
        help="--limit과 함께 쓸 시작 페이지. 순번은 목록 맨 앞을 1로 센다. "
        "--range와 함께 쓸 수 없습니다.",
    )
    parser.add_argument("--keyword", default="", help="제목 검색어")
    parser.add_argument(
        "--search-type",
        default="TITLE",
        choices=["TITLE", "CONTENT", "WRITER"],
        help="검색 범위",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="합친 PDF 경로. 주제가 하나일 때만 이 파일을 그대로 씁니다. "
        "여러 주제거나 생략하면 output/{categoryId}_{이름}_{시작}-{끝}.pdf 로 저장합니다.",
    )
    parser.add_argument(
        "--download-dir",
        type=Path,
        default=Path("downloads"),
        help="개별 PDF를 저장할 폴더. 주제별로 하위 폴더를 나눕니다. "
        "manifest.json에 받은 doc_id를 적어 두어, 다음 실행에서는 같은 문서를 다시 받지 않습니다.",
    )
    parser.add_argument("--workers", type=int, default=4, help="동시 다운로드 수")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.range is None and args.limit < 1:
        print("--limit 은 1 이상이어야 합니다.", file=sys.stderr)
        return 2
    if args.range is not None and args.start_page != 1:
        print("--range와 --start-page는 함께 쓸 수 없습니다. 순번 구간만 지정하세요.", file=sys.stderr)
        return 2
    if args.start_page < 1:
        print("--start-page 는 1 이상이어야 합니다.", file=sys.stderr)
        return 2

    needs_catalog = bool(args.category_id) or args.split_by_category or args.list_categories
    catalog: list[tuple[str, str]] = fetch_categories(args.cms_code) if needs_catalog else []
    catalog_map = dict(catalog)

    if args.list_categories:
        for category_id, name in catalog:
            print(f"{category_id}\t{name}")
        return 0

    selected = requested_category_ids(args.category_id)
    if args.split_by_category and not selected:
        targets = catalog
    elif selected:
        unknown = [category_id for category_id in selected if category_id not in catalog_map]
        if unknown:
            known = ", ".join(f"{category_id}({name})" for category_id, name in catalog)
            print(
                f"알 수 없는 categoryId: {', '.join(unknown)}\n사용 가능: {known}",
                file=sys.stderr,
            )
            return 2
        targets = [(category_id, catalog_map[category_id]) for category_id in selected]
    else:
        targets = [("", "")]

    fixed_window = args.range
    exit_code = 0
    for category_id, name in targets:
        if fixed_window is not None:
            start_index, end_index = fixed_window
        else:
            offset = items_before_page(
                args.cms_code,
                args.keyword,
                args.search_type,
                category_id,
                args.start_page,
            )
            start_index = offset + 1
            end_index = offset + args.limit
        code = run_one(
            cms_code=args.cms_code,
            keyword=args.keyword,
            search_type=args.search_type,
            category_id=category_id,
            category_name=name,
            start_index=start_index,
            end_index=end_index,
            output_spec=args.output,
            target_count=len(targets),
            download_dir=download_dir_for(args.download_dir, category_id),
            workers=args.workers,
        )
        exit_code = max(exit_code, code)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
