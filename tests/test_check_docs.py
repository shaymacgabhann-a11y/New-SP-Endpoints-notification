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
        self.assertEqual(snap["meta"]["page_count"], 4)  # guide page is not tracked
        by_key = {p["key"]: p for p in snap["pages"]}
        lc = by_key["/reference/list-clients-1"]
        self.assertEqual((lc["method"], lc["path"], lc["product"]), ("GET", "/v1/clients", "Core API"))
        self.assertEqual(lc["operation"]["parameters"], ["query:filter", "query:page"])
        self.assertEqual(lc["updated_at"], "2026-04-23T21:49:21.000Z")
        self.assertNotIn("/docs/getting-started", by_key)
        self.assertIn("query:filter", lc["fingerprint"]["params"])

        # 2. Site changes: expect a report + Slack payload (dry run prints it).
        code, out, err = run(self.v2, self.snapshot, self.report)
        self.assertEqual(code, 0, err)
        self.assertIn("changes: +2 -1 ~2", err)
        report = self.report.read_text()

        # Added
        self.assertIn("POST /api/public/v1/agreements", report)
        self.assertIn("POST /v1/backups/results", report)
        self.assertNotIn("API versioning policy", report)  # guides are ignored
        # Removed
        self.assertIn("DELETE /v1/evidence/{id}/requests/{reqId}", report)
        # Changed - semantic details
        self.assertIn("param added: `query:sort`", report)
        self.assertIn("responses added: `429`", report)
        self.assertIn("marked *deprecated*", report)
        self.assertNotIn("Getting started", report)  # guide prose change is ignored
        # Unchanged page is not reported
        self.assertNotIn("/v1/clients/{id}", report)
        # Grouped by product
        self.assertIn("### Backup Radar API", report)
        self.assertIn("### Lifecycle Manager API", report)

        # Slack payload is valid Block Kit-ish JSON with <= 50 blocks
        payload = json.loads(out[out.index("{\n"):])
        self.assertLessEqual(len(payload["blocks"]), 50)
        self.assertEqual(payload["blocks"][0]["type"], "header")
        self.assertIn("2 added, 1 removed, 2 changed", payload["text"])
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

    def test_old_snapshot_guides_are_not_reported_as_removed(self):
        run(self.v1, self.snapshot, self.report)
        snap = json.loads(self.snapshot.read_text())
        snap["pages"].append({"key": "/docs/old-guide", "title": "Old guide", "url": "u",
                              "description": "", "kind": "guide", "content_hash": "x"})
        self.snapshot.write_text(json.dumps(snap))
        code, out, err = run(self.v1, self.snapshot, self.report)
        self.assertEqual(code, 0, err)
        self.assertIn("no changes", err)

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


def endpoint_page(spec_op: dict, *, servers=None, schemas=None, intro="Lists widgets.",
                  key="/reference/w", product="Core API", path="/v1/widgets") -> "check_docs.Page":
    """Build an enriched endpoint Page from a single OpenAPI operation."""
    spec = {"openapi": "3.0.1", "info": {"title": product, "version": "v1"},
            "servers": servers or [{"url": "https://api.scalepad.com"}],
            "paths": {path: {"get": spec_op}},
            "components": {"schemas": schemas or {}}}
    md = (f"---\nupdatedAt: 2026-01-01\n---\n\n# Widgets\n\n{intro}\n\n# OpenAPI definition\n\n"
          f"```json\n{json.dumps(spec, indent=2)}\n```\n")
    page = check_docs.Page(key=key, title="List Widgets", url="https://e.test" + key, description="", kind="endpoint")
    check_docs.enrich_page(page, md)
    return page


WIDGET_SCHEMA = {"type": "object", "required": ["id"], "properties": {
    "id": {"type": "string", "format": "uuid"},
    "status": {"type": "string", "enum": ["active", "retired"], "description": "Lifecycle state."},
    "owner": {"$ref": "#/components/schemas/Owner"}}}
OWNER_SCHEMA = {"type": "object", "properties": {"name": {"type": "string"}}}


def widget_op(**overrides) -> dict:
    op = {"summary": "List Widgets", "description": "Retrieves a list of widgets for the tenant.",
          "parameters": [{"name": "page_size", "in": "query", "schema": {"type": "integer", "default": 50},
                          "description": "Items per page."}],
          "responses": {"200": {"description": "OK", "content": {"application/json": {"schema": {
              "type": "object", "properties": {"data": {"type": "array",
                                                        "items": {"$ref": "#/components/schemas/Widget"}}}}}}}}}
    op.update(overrides)
    return op


class DescribeChangeTest(unittest.TestCase):
    def schemas(self, widget=None, owner=None):
        return {"Widget": widget or WIDGET_SCHEMA, "Owner": owner or OWNER_SCHEMA}

    def test_field_level_details(self):
        old = endpoint_page(widget_op(), schemas=self.schemas())
        widget = json.loads(json.dumps(WIDGET_SCHEMA))
        widget["properties"]["status"]["enum"].append("archived")
        widget["properties"]["status"]["description"] = "Where the widget is in its lifecycle."
        widget["properties"]["cost"] = {"type": "number"}
        widget["required"].append("owner")
        owner = {"type": "object", "properties": {"name": {"type": "integer"}, "email": {"type": "string"}}}
        op = widget_op(description="Retrieves a paginated list of widgets for the tenant.")
        op["parameters"][0]["schema"] = {"type": "integer", "default": 100, "maximum": 500}
        op["parameters"].append({"name": "sort", "in": "query", "required": True, "schema": {"type": "string"}})
        new = endpoint_page(op, schemas=self.schemas(widget, owner))

        details = check_docs.describe_change(old, new)
        joined = "\n".join(details)
        self.assertIn("param added: `query:sort`", joined)
        self.assertIn("param `query:page_size`: default `50` → `100`, constraints `none` → `maximum=500`", joined)
        self.assertIn("`200` response field added: `data[].cost`, `data[].owner.email`", joined)
        self.assertIn("`200` response field `data[].owner`: now required", joined)
        self.assertIn("`200` response field `data[].owner.name`: type `string` → `integer`", joined)
        self.assertIn("`200` response field `data[].status`: enum values added `archived`, description reworded", joined)
        self.assertIn("description: “Retrieves a list of widgets for…” → “Retrieves a paginated list of widgets for…”", joined)
        self.assertNotIn("page content updated", joined)

    def test_nested_additions_collapse_to_parent(self):
        old = endpoint_page(widget_op(), schemas=self.schemas())
        widget = json.loads(json.dumps(WIDGET_SCHEMA))
        widget["properties"]["address"] = {"type": "object", "properties": {
            "city": {"type": "string"}, "zip": {"type": "string"}}}
        new = endpoint_page(widget_op(), schemas=self.schemas(widget))
        self.assertEqual(check_docs.describe_change(old, new),
                         ["`200` response field added: `data[].address` (+2 nested)"])

    def test_formatting_only_change_is_not_reported(self):
        old = endpoint_page(widget_op(), schemas=self.schemas())
        new = endpoint_page(widget_op(), schemas=self.schemas())
        new.content_hash = "different"  # e.g. whitespace / key order in the markdown
        diff = check_docs.compute_diff({old.key: old}, [new])
        self.assertTrue(diff.is_empty())
        self.assertEqual(diff.cosmetic, 1)

    def test_change_shared_by_many_endpoints_is_reported_once(self):
        old_pages, new_pages = {}, []
        for i in range(8):
            key = f"/reference/w{i}"
            old = endpoint_page(widget_op(), schemas=self.schemas(), key=key, path=f"/v1/w{i}")
            op = widget_op()
            if i == 0:
                op["parameters"].append({"name": "q", "in": "query", "schema": {"type": "string"}})
            new = endpoint_page(op, schemas=self.schemas(), key=key, path=f"/v1/w{i}", servers=[
                {"url": "https://api.scalepad.com"}, {"url": "https://api.eu.scalepad.com", "description": "EU"}])
            old_pages[key] = old
            new_pages.append(new)
        diff = check_docs.compute_diff(old_pages, new_pages)
        self.assertEqual(len(diff.changed), 8)
        self.assertEqual([(d, len(p)) for d, p in diff.shared],
                         [("servers added: `https://api.eu.scalepad.com (EU)`", 8)])
        self.assertEqual([c.details for c in diff.changed if c.details], [["param added: `query:q`"]])

        now = check_docs.datetime(2026, 1, 1, tzinfo=check_docs.timezone.utc)
        report = check_docs.render_markdown(diff, 8, "https://e.test", now)
        self.assertEqual(report.count("api.eu.scalepad.com"), 1)
        self.assertIn("**8 endpoints** (Core API)", report)
        self.assertIn("## Endpoint-specific changes (1)", report)
        payload = check_docs.build_slack_payload(diff, 8, "https://e.test", now)
        self.assertEqual(json.dumps(payload).count("api.eu.scalepad.com"), 1)

    def test_old_snapshot_without_fingerprint_falls_back(self):
        old = endpoint_page(widget_op(), schemas=self.schemas())
        old.fingerprint = {}
        new = endpoint_page(widget_op(), schemas=self.schemas())
        self.assertEqual(len(check_docs.describe_change(old, new)), 1)

    def test_page_text_change_when_it_previously_matched_description(self):
        op = widget_op()
        old = endpoint_page(op, schemas=self.schemas(), intro=op["description"])
        self.assertEqual(old.fingerprint["prose"], "")  # deduped against the description
        new = endpoint_page(op, schemas=self.schemas(), intro=op["description"] + " Results are cached.")
        self.assertEqual(check_docs.describe_change(old, new),
                         ["page text: “…widgets for the tenant.” → “…widgets for the tenant. Results are cached.”"])

    def test_text_change(self):
        self.assertEqual(check_docs.text_change("a b c d", "a b X d"), "“a b c d” → “a b X d”")
        self.assertIsNone(check_docs.text_change("same", "same"))


if __name__ == "__main__":
    unittest.main()
