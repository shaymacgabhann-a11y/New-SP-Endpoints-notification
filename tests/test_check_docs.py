"""
End-to-end test: serve fixture snapshots of the docs site over local HTTP and run
check_docs.py through baseline -> changed -> unchanged. Run with:

    python3 -m unittest -v tests/test_check_docs.py
"""

from __future__ import annotations

import functools
import http.server
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import check_docs  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_):  # silence request logging
        pass


def serve(directory: Path) -> tuple[http.server.ThreadingHTTPServer, str]:
    handler = functools.partial(_Quiet, directory=str(directory))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def run(base_url: str, snapshot: Path, report: Path) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = check_docs.main(["--base-url", base_url, "--snapshot", str(snapshot),
                                "--report", str(report), "--dry-run", "--concurrency", "4"])
    return code, out.getvalue(), err.getvalue()


class RateLimitedHandler(http.server.BaseHTTPRequestHandler):
    """Returns 429 for the first N requests to any path, then 200 with a fixed body."""
    fail_times = 0
    hits = 0
    retry_after = None

    def do_GET(self):
        type(self).hits += 1
        if type(self).hits <= type(self).fail_times:
            self.send_response(429)
            if type(self).retry_after is not None:
                self.send_header("Retry-After", str(type(self).retry_after))
            self.end_headers()
            return
        body = b"ok"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


class HttpGetRateLimitTest(unittest.TestCase):
    def test_retries_429_and_honours_retry_after(self):
        RateLimitedHandler.hits = 0
        RateLimitedHandler.fail_times = 2
        RateLimitedHandler.retry_after = 0  # keep the test instant
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), RateLimitedHandler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            with patch("check_docs.time.sleep"):
                result = check_docs.http_get(f"http://127.0.0.1:{srv.server_address[1]}/x")
            self.assertEqual(result, "ok")
            self.assertEqual(RateLimitedHandler.hits, 3)
        finally:
            srv.shutdown()
            srv.server_close()

    def test_gives_up_after_rate_limit_retries_exhausted(self):
        RateLimitedHandler.hits = 0
        RateLimitedHandler.fail_times = 999
        RateLimitedHandler.retry_after = None
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), RateLimitedHandler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            with patch("check_docs.time.sleep"):
                with self.assertRaises(Exception):
                    check_docs.http_get(f"http://127.0.0.1:{srv.server_address[1]}/x", rate_limit_retries=3)
            self.assertEqual(RateLimitedHandler.hits, 4)  # initial attempt + 3 retries
        finally:
            srv.shutdown()
            srv.server_close()


class CheckDocsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v1_srv, cls.v1 = serve(FIXTURES / "v1")
        cls.v2_srv, cls.v2 = serve(FIXTURES / "v2")

    @classmethod
    def tearDownClass(cls):
        for srv in (cls.v1_srv, cls.v2_srv):
            srv.shutdown()
            srv.server_close()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.snapshot = Path(self.tmp.name) / "snapshot.json"
        self.report = Path(self.tmp.name) / "report.md"

    def tearDown(self):
        self.tmp.cleanup()

    def test_baseline_then_changes_then_quiet(self):
        # 1. Baseline: creates snapshot, reports nothing.
        code, out, err = run(self.v1, self.snapshot, self.report)
        self.assertEqual(code, 0, err)
        self.assertIn("baseline established", err)
        self.assertEqual(out, "")
        snap = json.loads(self.snapshot.read_text())
        self.assertEqual(snap["meta"]["page_count"], 5)
        by_key = {p["key"]: p for p in snap["pages"]}
        lc = by_key["/reference/list-clients-1"]
        self.assertEqual((lc["method"], lc["path"], lc["product"]), ("GET", "/v1/clients", "Core API"))
        self.assertEqual(lc["operation"]["parameters"], ["query:filter", "query:page"])
        self.assertEqual(lc["updated_at"], "2026-04-23T21:49:21.000Z")
        self.assertEqual(by_key["/docs/getting-started"]["kind"], "guide")

        # 2. Site changes: expect a report + Slack payload (dry run prints it).
        code, out, err = run(self.v2, self.snapshot, self.report)
        self.assertEqual(code, 0, err)
        self.assertIn("changes: +3 -1 ~3", err)
        report = self.report.read_text()

        # Added
        self.assertIn("POST /api/public/v1/agreements", report)
        self.assertIn("POST /v1/backups/results", report)
        self.assertIn("API versioning policy", report)
        # Removed
        self.assertIn("DELETE /v1/evidence/{id}/requests/{reqId}", report)
        # Changed — semantic details
        self.assertIn("params added: `query:sort`", report)
        self.assertIn("responses added: `429`", report)
        self.assertIn("marked *deprecated*", report)
        self.assertIn("page content updated", report)  # guide prose change
        # Unchanged page is not reported
        self.assertNotIn("/v1/clients/{id}", report)
        # Grouped by product
        self.assertIn("### Backup Radar API", report)
        self.assertIn("### Lifecycle Manager API", report)

        # Slack payload is valid Block Kit-ish JSON with <= 50 blocks
        payload = json.loads(out[out.index("{\n"):])
        self.assertLessEqual(len(payload["blocks"]), 50)
        self.assertEqual(payload["blocks"][0]["type"], "header")
        self.assertIn("3 added, 1 removed, 3 changed", payload["text"])
        flat = json.dumps(payload)
        self.assertIn("apipublicv1agreementscreate|POST /api/public/v1/agreements>", flat)

        # 3. Re-run against the same site: no changes, no output.
        code, out, err = run(self.v2, self.snapshot, self.report)
        self.assertEqual(code, 0, err)
        self.assertIn("no changes", err)
        self.assertEqual(out, "")

    def test_parse_llms_ignores_headers_and_dedupes(self):
        text = (FIXTURES / "v1" / "llms.txt").read_text() + "\n- [List Clients](https://developer.scalepad.com/reference/list-clients-1.md): dup\n"
        pages = check_docs.parse_llms(text, "https://example.test")
        self.assertEqual(len(pages), 5)
        self.assertTrue(all(p.url.startswith("https://example.test/") for p in pages))
        self.assertEqual({p.kind for p in pages}, {"guide", "endpoint"})

    def test_carry_forward_failed_preserves_last_known_good_data(self):
        good = check_docs.Page(key="/reference/x", title="X", url="https://e.test/reference/x",
                                description="", kind="endpoint", content_hash="abc123",
                                product="Core API", method="GET", path="/v1/x")
        old_pages = {"/reference/x": good, "/reference/y": check_docs.Page(
            key="/reference/y", title="Y", url="https://e.test/reference/y", description="", kind="endpoint")}
        failed_fetch = check_docs.Page(key="/reference/x", title="X", url="https://e.test/reference/x",
                                        description="", kind="endpoint", fetch_error="HTTPError: 429")
        brand_new_failed = check_docs.Page(key="/reference/z", title="Z", url="https://e.test/reference/z",
                                            description="", kind="endpoint", fetch_error="HTTPError: 429")
        pages = [failed_fetch, brand_new_failed]

        carried = check_docs.carry_forward_failed(pages, old_pages)

        self.assertEqual(carried, 1)
        # Known page: fully restored to its last-good record, fetch_error cleared.
        self.assertEqual(pages[0].content_hash, "abc123")
        self.assertIsNone(pages[0].fetch_error)
        self.assertEqual(pages[0].method, "GET")
        # Brand-new page with no prior record: nothing to carry forward, left as-is.
        self.assertEqual(pages[1].key, "/reference/z")
        self.assertEqual(pages[1].fetch_error, "HTTPError: 429")

    def test_missing_llms_does_not_clobber_snapshot(self):
        self.snapshot.write_text(json.dumps({"meta": {}, "pages": [{"key": "/x", "title": "x", "url": "u", "description": "", "kind": "guide"}]}))
        with tempfile.TemporaryDirectory() as empty:
            srv, url = serve(Path(empty))
            try:
                out, err = io.StringIO(), io.StringIO()
                with redirect_stdout(out), redirect_stderr(err):
                    with self.assertRaises(Exception):
                        check_docs.main(["--base-url", url, "--snapshot", str(self.snapshot), "--dry-run"])
            finally:
                srv.shutdown()
                srv.server_close()
        self.assertIn('"key": "/x"', self.snapshot.read_text())


if __name__ == "__main__":
    unittest.main()
