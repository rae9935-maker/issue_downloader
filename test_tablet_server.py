"""태블릿 화면 서버의 요청 검증과 진행 표시를 확인한다. 사이트에는 접속하지 않는다."""

from __future__ import annotations

import json
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import tablet_server
from tablet_server import App, handler_for


class TabletServerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        root = Path(self.tmp.name)
        self.output_dir = root / "output"
        self.app = App(root / "downloads", self.output_dir, "테스트 폴더")
        self.app.catalog["CM0018"] = [("b1", "재정금융"), ("a2", "법제사법")]
        self.httpd = tablet_server.ThreadingHTTPServer(("127.0.0.1", 0), handler_for(self.app))
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.thread.join(timeout=3)
        self.httpd.server_close()
        self.tmp.cleanup()

    def request(self, method: str, path: str, body: dict | None = None, raw: bytes | None = None):
        data = raw
        headers = {}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=data,
            method=method,
            headers=headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers), exc.read()

    def test_page_is_tablet_layout(self) -> None:
        status, _headers, body = self.request("GET", "/")
        text = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn("width=device-width", text)
        self.assertIn("주제를 누르고", text)
        self.assertIn("이 구간 받기", text)

    def test_rejects_missing_range(self) -> None:
        status, _headers, body = self.request("POST", "/api/jobs", {"categoryId": "b1"})
        self.assertEqual(status, 400)
        self.assertIn("시작 번호", json.loads(body)["error"])

    def test_rejects_reversed_range_and_huge_batch(self) -> None:
        status, _headers, body = self.request(
            "POST",
            "/api/jobs",
            {"categoryId": "b1", "start": 20, "end": 10},
        )
        self.assertEqual(status, 400)
        status, _headers, body = self.request(
            "POST",
            "/api/jobs",
            {"categoryId": "b1", "start": 1, "end": 500},
        )
        self.assertEqual(status, 400)
        self.assertIn("400", json.loads(body)["error"])

    def test_rejects_unknown_category_without_network(self) -> None:
        status, _headers, body = self.request(
            "POST",
            "/api/jobs",
            {"categoryId": "z9", "start": 1, "end": 2},
        )
        self.assertEqual(status, 400)
        self.assertIn("없는 주제", json.loads(body)["error"])

    def test_job_reports_progress_and_serves_pdf(self) -> None:
        def fake_run_one(**kwargs):
            kwargs["log"]("[1/2] #1 첫번째")
            kwargs["log"]("[2/2] #2 두번째")
            kwargs["output_spec"].write_bytes(b"%PDF-1.4\n")
            kwargs["log"](
                "완료: b1 재정금융 2개 문서, 4페이지, 0.1MB -> "
                f"{kwargs['output_spec']} (새로 받음 2, 이미 있던 파일 0)"
            )
            return 0

        with patch("tablet_server.run_one", side_effect=fake_run_one):
            status, _headers, body = self.request(
                "POST",
                "/api/jobs",
                {"cmsCode": "CM0018", "categoryId": "b1", "start": 10, "end": 11, "keyword": ""},
            )
            self.assertEqual(status, 202)
            deadline = time.time() + 3
            payload = {}
            while time.time() < deadline:
                _status, _headers, raw = self.request("GET", "/api/status")
                payload = json.loads(raw)
                if not payload["running"]:
                    break
                time.sleep(0.02)
            self.assertEqual(payload["phase"], "done")
            self.assertEqual(payload["done"], 2)
            self.assertTrue(payload["pdf"].endswith(".pdf"))
            pdf_path = "/api/pdf/" + urllib.parse.quote(payload["pdf"])
            pdf_status, headers, pdf = self.request("GET", pdf_path)
            self.assertEqual(pdf_status, 200)
            self.assertEqual(pdf, b"%PDF-1.4\n")
            self.assertIn("application/pdf", headers["Content-Type"])

    def test_blocks_path_escape(self) -> None:
        outside = Path(self.tmp.name) / "secret.pdf"
        outside.write_bytes(b"%PDF-secret")
        status, _headers, _body = self.request("GET", "/api/pdf/..%2Fsecret.pdf")
        self.assertEqual(status, 404)

    def test_rejects_second_job_while_running(self) -> None:
        with self.app.lock:
            self.app.state["running"] = True
        status, _headers, body = self.request(
            "POST",
            "/api/jobs",
            {"categoryId": "b1", "start": 1, "end": 2},
        )
        self.assertEqual(status, 409)
        self.assertIn("이미 받는 중", json.loads(body)["error"])

    def test_library_count_reads_manifest(self) -> None:
        folder = self.app.download_dir / "b1"
        folder.mkdir(parents=True)
        (folder / "manifest.json").write_text('{"doc": "file.pdf"}\n', encoding="utf-8")
        status, _headers, body = self.request("GET", "/api/library?categoryId=b1")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["count"], 1)
        status, _headers, body = self.request("GET", "/api/library?categoryId=../b1")
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
