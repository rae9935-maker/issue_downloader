#!/usr/bin/env python3
"""국회입법조사처 보고서 목록을 받아 하나의 PDF로 합친다.

사이트 목록의 [다운로드]와 같은 주소(fileDownload2.do)를 사용한다.
"""

from __future__ import annotations

import argparse
import html
import re
import sys
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


def collect_reports(
    cms_code: str,
    limit: int,
    start_page: int,
    keyword: str,
    search_type: str,
) -> list[Report]:
    reports: list[Report] = []
    page = start_page
    while len(reports) < limit:
        query = urllib.parse.urlencode(
            {
                "page": page,
                "cmsCode": cms_code,
                "categoryId": "",
                "searchType": search_type,
                "searchKeyword": keyword,
            }
        )
        body = fetch(f"{LIST_URL}?{query}").decode("utf-8", errors="replace")
        rows = parse_list_page(body)
        if not rows:
            break
        for seq, title, doc_id, filename in rows:
            reports.append(
                Report(
                    index=len(reports) + 1,
                    seq=seq,
                    title=title,
                    doc_id=doc_id,
                    filename=filename,
                )
            )
            if len(reports) >= limit:
                break
        page += 1
        time.sleep(0.15)
    return reports


def safe_filename(name: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\r\n]+', "_", name).strip(" .")
    return cleaned[:140] or "report"


def report_path(download_dir: Path, report: Report) -> Path:
    return download_dir / f"{report.index:04d}_{report.doc_id}_{safe_filename(report.filename)}"


def download_one(report: Report, dest: Path) -> tuple[Report, str | None]:
    if dest.exists() and dest.stat().st_size > 500:
        with dest.open("rb") as handle:
            head = handle.read(5)
        if head == b"%PDF-":
            return report, None
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
        return report, str(exc)
    if not data.startswith(b"%PDF-"):
        return report, f"PDF가 아닌 응답 ({len(data)} bytes)"
    dest.write_bytes(data)
    return report, None


def download_all(reports: list[Report], download_dir: Path, workers: int) -> list[str]:
    download_dir.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [
            pool.submit(download_one, report, report_path(download_dir, report))
            for report in reports
        ]
        done = 0
        for future in as_completed(futures):
            report, error = future.result()
            done += 1
            if error:
                failures.append(f"{report.bookmark}: {error}")
                print(f"[{done}/{len(reports)}] 실패 {report.doc_id} {error}", file=sys.stderr)
            else:
                print(f"[{done}/{len(reports)}] {report.bookmark}")
    return failures


def merge_pdfs(reports: list[Report], download_dir: Path, output: Path) -> tuple[int, int]:
    writer = PdfWriter()
    merged = 0
    skipped = 0
    for report in reports:
        path = report_path(download_dir, report)
        if not path.exists():
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="국회입법조사처 보고서를 내려받아 하나의 PDF로 합칩니다."
    )
    parser.add_argument(
        "--cms-code",
        default="CM0018",
        help="목록 코드. CM0018은 이슈와논점 (기본값)",
    )
    parser.add_argument("--limit", type=int, default=100, help="받을 문서 수 (기본값 100)")
    parser.add_argument("--start-page", type=int, default=1, help="목록 시작 페이지")
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
        default=Path("output/nars_merged.pdf"),
        help="합친 PDF 경로",
    )
    parser.add_argument(
        "--download-dir",
        type=Path,
        default=Path("downloads"),
        help="개별 PDF를 저장할 폴더. 이미 있으면 다시 받지 않습니다.",
    )
    parser.add_argument("--workers", type=int, default=4, help="동시 다운로드 수")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.limit < 1:
        print("--limit 은 1 이상이어야 합니다.", file=sys.stderr)
        return 2
    print(f"목록 수집: cmsCode={args.cms_code} limit={args.limit} page={args.start_page}")
    reports = collect_reports(
        cms_code=args.cms_code,
        limit=args.limit,
        start_page=args.start_page,
        keyword=args.keyword,
        search_type=args.search_type,
    )
    if not reports:
        print("목록에서 다운로드 가능한 문서를 찾지 못했습니다.", file=sys.stderr)
        return 1
    print(f"{len(reports)}건 수집. 다운로드 시작 (동시 {args.workers})")
    failures = download_all(reports, args.download_dir, args.workers)
    merged, pages = merge_pdfs(reports, args.download_dir, args.output)
    size_mb = args.output.stat().st_size / (1024 * 1024)
    print(
        f"완료: {merged}개 문서, {pages}페이지, {size_mb:.1f}MB -> {args.output}"
    )
    if failures:
        print(f"실패한 다운로드 {len(failures)}건", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
