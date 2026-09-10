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
