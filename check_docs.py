#!/usr/bin/env python3
"""
Watch developer.scalepad.com for documentation changes and report them to Slack.

How it works
------------
1. Fetch https://developer.scalepad.com/llms.txt — ReadMe's index of every published
   page (guides + one page per API endpoint).
2. Fetch each page's markdown (`<url>.md`). Endpoint pages carry an `updatedAt`
   frontmatter field and embed the endpoint's OpenAPI definition, so we can extract
   HTTP method, path, product, parameters, request fields and response codes.
3. Compare against the previous snapshot (state/snapshot.json) and report:
     - endpoints added / removed
     - endpoints changed (with a compact semantic diff)
     - guide pages added / removed / changed
4. Post a Slack Block Kit message to $SLACK_WEBHOOK_URL (if set) and write
   state/last_report.md. Then save the new snapshot.

The first run establishes a baseline and posts nothing.

Stdlib only — no third-party dependencies.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field, asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_BASE_URL = "https://developer.scalepad.com"
SNAPSHOT_PATH = Path("state/snapshot.json")
REPORT_PATH = Path("state/last_report.md")
USER_AGENT = "scalepad-docs-watch/1.0 (+https://github.com/shaymacgabhann-a11y/New-SP-Endpoints-notification)"

# Slack allows 50 blocks per message; keep a margin.
MAX_BLOCKS = 45
MAX_ITEMS_PER_SECTION = 25

LLMS_LINE_RE = re.compile(r"^- \[(?P<title>[^\]]+)\]\((?P<url>[^)\s]+)\)(?::\s*(?P<desc>.*))?$")
FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)
OPENAPI_BLOCK_RE = re.compile(r"# OpenAPI definition\s*\n```json\s*\n(.*?)\n```", re.S)
HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")


# --------------------------------------------------------------------------- #
# Fetching
# --------------------------------------------------------------------------- #

def http_get(url: str, retries: int = 3, timeout: int = 30, rate_limit_retries: int = 6) -> str:
    last_err: Exception | None = None
    attempt = 0
    rate_limit_attempt = 0
    while True:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/plain, text/markdown, */*"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:  # noqa: PERF203
            last_err = e
            if isinstance(e, urllib.error.HTTPError) and e.code == 429:
                # Rate limited: back off longer and more patiently than a plain retry,
                # honouring Retry-After when the server sends one.
                rate_limit_attempt += 1
                if rate_limit_attempt > rate_limit_retries:
                    raise
                retry_after = None
                try:
                    retry_after = float(e.headers.get("Retry-After")) if e.headers else None
                except (TypeError, ValueError):
                    retry_after = None
                delay = retry_after if retry_after is not None else min(2.0 * (2 ** (rate_limit_attempt - 1)), 30.0)
                time.sleep(delay)
                continue
            # Don't retry other hard 4xx.
            if isinstance(e, urllib.error.HTTPError) and 400 <= e.code < 500:
                raise
            attempt += 1
            if attempt >= retries:
                raise
            time.sleep(1.5 * attempt)
    assert last_err is not None
    raise last_err


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #

@dataclass
class Page:
    key: str                      # stable id: URL path without .md
    title: str
    url: str                      # canonical page URL (no .md)
    description: str
    kind: str                     # "endpoint" | "guide"
    updated_at: str | None = None
    content_hash: str | None = None
    product: str | None = None    # e.g. "Core API", "Lifecycle Manager API"
    method: str | None = None     # e.g. "GET"
    path: str | None = None       # e.g. "/v1/clients"
    operation: dict[str, Any] = field(default_factory=dict)  # compact semantic summary
    fetch_error: str | None = None

    @property
    def label(self) -> str:
        if self.method and self.path:
            return f"`{self.method} {self.path}` — {self.title}"
        return self.title


def parse_llms(text: str, base_url: str) -> list[Page]:
    pages: list[Page] = []
    seen: set[str] = set()
    for raw in text.splitlines():
        m = LLMS_LINE_RE.match(raw.strip())
        if not m:
            continue
        url = m.group("url").strip()
        if url.endswith(".md"):
            url = url[:-3]
        # Normalise to the configured base so fixtures/tests can override host.
        path = re.sub(r"^https?://[^/]+", "", url)
        url = base_url.rstrip("/") + path
        key = path
        if key in seen:
            continue
        seen.add(key)
        kind = "endpoint" if path.startswith("/reference/") else "guide"
        pages.append(Page(key=key, title=m.group("title").strip(), url=url,
                          description=(m.group("desc") or "").strip(), kind=kind))
    return pages


def _resolve_ref(spec: dict, obj: Any, depth: int = 0) -> Any:
    """Resolve a local $ref one level (enough for top-level property names)."""
    if depth > 5 or not isinstance(obj, dict) or "$ref" not in obj:
        return obj
    ref = obj["$ref"]
    if not ref.startswith("#/"):
        return obj
    node: Any = spec
    for part in ref[2:].split("/"):
        if not isinstance(node, dict) or part not in node:
            return obj
        node = node[part]
    return _resolve_ref(spec, node, depth + 1)


def _schema_props(spec: dict, schema: Any) -> list[str]:
    schema = _resolve_ref(spec, schema)
    if not isinstance(schema, dict):
        return []
    props: list[str] = []
    if isinstance(schema.get("properties"), dict):
        props.extend(schema["properties"].keys())
    for combo in ("allOf", "oneOf", "anyOf"):
        for sub in schema.get(combo) or []:
            props.extend(_schema_props(spec, sub))
    if schema.get("type") == "array" and "items" in schema:
        props.extend(f"[].{p}" for p in _schema_props(spec, schema["items"]))
    return sorted(set(props))


def summarise_operation(spec: dict, op: dict) -> dict[str, Any]:
    params = []
    for p in op.get("parameters") or []:
        p = _resolve_ref(spec, p)
        if isinstance(p, dict) and "name" in p:
            params.append(f"{p.get('in','?')}:{p['name']}" + ("*" if p.get("required") else ""))
    body_props: list[str] = []
    rb = _resolve_ref(spec, op.get("requestBody"))
    if isinstance(rb, dict):
        for media in (rb.get("content") or {}).values():
            body_props.extend(_schema_props(spec, media.get("schema")))
    responses = sorted((op.get("responses") or {}).keys())
    return {
        "summary": op.get("summary") or "",
        "deprecated": bool(op.get("deprecated")),
        "parameters": sorted(set(params)),
        "request_fields": sorted(set(body_props)),
        "responses": responses,
        "tags": sorted(op.get("tags") or []),
    }


def enrich_page(page: Page, markdown: str) -> None:
    fm = FRONTMATTER_RE.match(markdown)
    body = markdown
    if fm:
        body = markdown[fm.end():]
        for line in fm.group(1).splitlines():
            if line.startswith("updatedAt:"):
                page.updated_at = line.split(":", 1)[1].strip()
    # Strip the ReadMe boilerplate sentence so it never triggers a diff.
    body = re.sub(r"^Fetch the complete documentation index at:.*?\n", "", body, count=1, flags=re.M)
    page.content_hash = hashlib.sha256(body.strip().encode()).hexdigest()[:16]

    m = OPENAPI_BLOCK_RE.search(markdown)
    if not m:
        return
    try:
        spec = json.loads(m.group(1))
    except json.JSONDecodeError:
        return
    page.product = (spec.get("info") or {}).get("title")
    paths = spec.get("paths") or {}
    for path, methods in paths.items():
        if not isinstance(methods, dict):
            continue
        for method, op in methods.items():
            if method.lower() in HTTP_METHODS and isinstance(op, dict):
                page.method = method.upper()
                page.path = path
                page.operation = summarise_operation(spec, op)
                return  # one operation per page


def carry_forward_failed(pages: list[Page], old_pages: dict[str, Page]) -> int:
    """Replace any page that failed to fetch this run with its last known-good
    record from the previous snapshot, in place. Returns how many were carried.

    A page that failed to fetch must not overwrite its last known-good record —
    that would both erase real data and, since the diff skips any page with a
    fetch_error on either side, permanently swallow the next real change to it
    (comparing against a blanked-out entry forever). Only genuinely new pages
    (never seen before) keep their fetch_error, since there is nothing to carry
    forward for them.
    """
    carried = 0
    for i, p in enumerate(pages):
        if p.fetch_error and p.key in old_pages:
            pages[i] = replace(old_pages[p.key])
            carried += 1
    return carried


def fetch_pages(pages: list[Page], concurrency: int, log) -> None:
    def work(p: Page) -> None:
        try:
            enrich_page(p, http_get(p.url + ".md"))
        except Exception as e:  # noqa: BLE001
            p.fetch_error = f"{type(e).__name__}: {e}"

    with cf.ThreadPoolExecutor(max_workers=concurrency) as ex:
        list(ex.map(work, pages))
    errors = [p for p in pages if p.fetch_error]
    if errors:
        log(f"warning: {len(errors)} page(s) failed to fetch")
        for p in errors[:10]:
            log(f"  {p.url}: {p.fetch_error}")


# --------------------------------------------------------------------------- #
# Diffing
# --------------------------------------------------------------------------- #

@dataclass
class Change:
    page: Page
    details: list[str]


@dataclass
class Diff:
    added: list[Page]
    removed: list[Page]
    changed: list[Change]

    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.changed)


def _set_delta(label: str, old: list[str], new: list[str]) -> list[str]:
    o, n = set(old), set(new)
    out = []
    if n - o:
        out.append(f"{label} added: " + ", ".join(f"`{x}`" for x in sorted(n - o)))
    if o - n:
        out.append(f"{label} removed: " + ", ".join(f"`{x}`" for x in sorted(o - n)))
    return out


def describe_change(old: Page, new: Page) -> list[str]:
    d: list[str] = []
    if old.method != new.method or old.path != new.path:
        d.append(f"route changed: `{old.method} {old.path}` → `{new.method} {new.path}`")
    if old.title != new.title:
        d.append(f"title: “{old.title}” → “{new.title}”")
    oo, no = old.operation or {}, new.operation or {}
    d += _set_delta("params", oo.get("parameters", []), no.get("parameters", []))
    d += _set_delta("request fields", oo.get("request_fields", []), no.get("request_fields", []))
    d += _set_delta("responses", oo.get("responses", []), no.get("responses", []))
    if oo.get("deprecated") != no.get("deprecated"):
        d.append("marked *deprecated*" if no.get("deprecated") else "no longer deprecated")
    if not d:
        if old.description != new.description or oo.get("summary") != no.get("summary"):
            d.append("description text updated")
        else:
            d.append("page content updated (schema details / examples / prose)")
    return d


def compute_diff(old_pages: dict[str, Page], new_pages: list[Page]) -> Diff:
    new_by_key = {p.key: p for p in new_pages}
    added = [p for k, p in new_by_key.items() if k not in old_pages]
    removed = [p for k, p in old_pages.items() if k not in new_by_key]
    changed: list[Change] = []
    for k, new in new_by_key.items():
        old = old_pages.get(k)
        if not old or new.fetch_error or old.fetch_error:
            continue  # don't report a change we can't verify
        if old.content_hash != new.content_hash:
            changed.append(Change(new, describe_change(old, new)))

    def sort_key(p: Page):
        return (p.kind != "endpoint", p.product or "", p.path or "", p.method or "", p.title)

    added.sort(key=sort_key)
    removed.sort(key=sort_key)
    changed.sort(key=lambda c: sort_key(c.page))
    return Diff(added, removed, changed)


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #

def _group_by_product(pages: list[Page]) -> dict[str, list[Page]]:
    groups: dict[str, list[Page]] = {}
    for p in pages:
        groups.setdefault(p.product or ("Guides" if p.kind == "guide" else "Other"), []).append(p)
    return dict(sorted(groups.items()))


def render_markdown(diff: Diff, total: int, base_url: str, now: datetime) -> str:
    lines = [f"# ScalePad developer docs — changes detected {now:%Y-%m-%d %H:%M UTC}", ""]
    lines.append(f"Tracking {total} pages at {base_url}. "
                 f"**{len(diff.added)} added · {len(diff.removed)} removed · {len(diff.changed)} changed**")
    lines.append("")

    def section(title: str, pages: list[Page], details: dict[str, list[str]] | None = None):
        if not pages:
            return
        lines.append(f"## {title} ({len(pages)})")
        for product, group in _group_by_product(pages).items():
            lines.append(f"### {product}")
            for p in group:
                lines.append(f"- [{p.label.replace('`', '')}]({p.url})")
                if p.kind == "endpoint" and not p.method and title.startswith("Added"):
                    lines.append("  - (no OpenAPI block found on page)")
                for d in (details or {}).get(p.key, []):
                    lines.append(f"  - {d}")
            lines.append("")

    section("Added", diff.added)
    section("Removed", diff.removed)
    section("Changed", [c.page for c in diff.changed], {c.page.key: c.details for c in diff.changed})
    return "\n".join(lines).rstrip() + "\n"


def _md_link(p: Page) -> str:
    text = f"{p.method} {p.path}" if p.method and p.path else p.title
    return f"<{p.url}|{text}>" + (f" — {p.title}" if p.method else "")


def build_slack_payload(diff: Diff, total: int, base_url: str, now: datetime) -> dict:
    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": "ScalePad Developer Docs — changes detected", "emoji": True}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text":
            f"{now:%b %d, %Y %H:%M UTC} · tracking {total} pages · "
            f"*{len(diff.added)} added* · *{len(diff.removed)} removed* · *{len(diff.changed)} changed*"}]},
        {"type": "divider"},
    ]

    def add_section(emoji: str, title: str, pages: list[Page], details: dict[str, list[str]] | None = None):
        if not pages:
            return
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"{emoji} *{title}* ({len(pages)})"}})
        shown = 0
        for product, group in _group_by_product(pages).items():
            text_lines = [f"*{product}*"]
            for p in group:
                if shown >= MAX_ITEMS_PER_SECTION:
                    break
                text_lines.append(f"• {_md_link(p)}")
                for d in (details or {}).get(p.key, [])[:4]:
                    text_lines.append(f"      ◦ {d}")
                shown += 1
            text = "\n".join(text_lines)
            if len(text) > 2900:
                text = text[:2850] + "\n…"
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text}})
            if len(blocks) >= MAX_BLOCKS - 2:
                break
        remaining = len(pages) - shown
        if remaining > 0:
            blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"…and {remaining} more — see the full report in the repo."}]})

    add_section(":new:", "New endpoints / pages", diff.added)
    add_section(":wastebasket:", "Removed", diff.removed)
    add_section(":pencil2:", "Changed", [c.page for c in diff.changed], {c.page.key: c.details for c in diff.changed})

    blocks.append({"type": "divider"})
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text":
        f"Source: <{base_url}/llms.txt|llms.txt> · <{base_url}/changelog|Changelog> · "
        f"<https://github.com/shaymacgabhann-a11y/New-SP-Endpoints-notification|watcher repo>"}]})

    summary = (f"ScalePad docs: {len(diff.added)} added, {len(diff.removed)} removed, "
               f"{len(diff.changed)} changed")
    return {"text": summary, "blocks": blocks[:50]}


def post_to_slack(webhook_url: str, payload: dict) -> None:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(webhook_url, data=data, headers={"Content-Type": "application/json", "User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode()
        if resp.status >= 300 or body.strip() not in ("ok", ""):
            raise RuntimeError(f"Slack webhook returned {resp.status}: {body}")


# --------------------------------------------------------------------------- #
# Snapshot I/O
# --------------------------------------------------------------------------- #

def load_snapshot(path: Path) -> tuple[dict[str, Page], dict]:
    if not path.exists():
        return {}, {}
    raw = json.loads(path.read_text())
    pages = {}
    for item in raw.get("pages", []):
        item.pop("label", None)
        pages[item["key"]] = Page(**item)
    return pages, raw.get("meta", {})


def save_snapshot(path: Path, pages: list[Page], meta: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"meta": meta, "pages": [asdict(p) for p in sorted(pages, key=lambda p: p.key)]}
    path.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default=os.environ.get("DOCS_BASE_URL", DEFAULT_BASE_URL))
    ap.add_argument("--snapshot", type=Path, default=SNAPSHOT_PATH)
    ap.add_argument("--report", type=Path, default=REPORT_PATH)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--dry-run", action="store_true", help="never post to Slack, print payload instead")
    ap.add_argument("--no-save", action="store_true", help="don't update the snapshot")
    ap.add_argument("--webhook", default=os.environ.get("SLACK_WEBHOOK_URL", ""),
                    help="Slack incoming webhook URL (default: $SLACK_WEBHOOK_URL)")
    args = ap.parse_args(argv)

    log = lambda *a: print(*a, file=sys.stderr)  # noqa: E731
    now = datetime.now(timezone.utc)
    base_url = args.base_url.rstrip("/")

    log(f"fetching {base_url}/llms.txt")
    pages = parse_llms(http_get(f"{base_url}/llms.txt"), base_url)
    if not pages:
        log("error: llms.txt parsed to zero pages — aborting without touching the snapshot")
        return 2
    log(f"{len(pages)} pages listed; fetching markdown…")
    fetch_pages(pages, args.concurrency, log)

    failed = sum(1 for p in pages if p.fetch_error)
    if failed > len(pages) * 0.25:
        log(f"error: {failed}/{len(pages)} pages failed to fetch — treating run as unreliable, snapshot untouched")
        return 3

    old_pages, old_meta = load_snapshot(args.snapshot)
    meta = {"base_url": base_url, "checked_at": now.isoformat(), "page_count": len(pages),
            "previous_checked_at": old_meta.get("checked_at")}

    carried = carry_forward_failed(pages, old_pages)
    if carried:
        log(f"carried forward last known-good data for {carried} page(s) that failed to fetch this run")

    if not old_pages:
        log("no previous snapshot — baseline established, nothing to report")
        if not args.no_save:
            save_snapshot(args.snapshot, pages, meta)
        return 0

    diff = compute_diff(old_pages, pages)
    if diff.is_empty():
        log("no changes")
        if not args.no_save:
            save_snapshot(args.snapshot, pages, meta)
        return 0

    log(f"changes: +{len(diff.added)} -{len(diff.removed)} ~{len(diff.changed)}")
    report = render_markdown(diff, len(pages), base_url, now)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report)
    print(report)

    payload = build_slack_payload(diff, len(pages), base_url, now)
    webhook = args.webhook.strip()
    if args.dry_run or not webhook or "hooks.slack.com" not in webhook:
        if not args.dry_run:
            log("SLACK_WEBHOOK_URL not set (or placeholder) — printing payload instead of posting")
        print(json.dumps(payload, indent=2))
    else:
        post_to_slack(webhook, payload)
        log("posted to Slack")

    if not args.no_save:
        save_snapshot(args.snapshot, pages, meta)
    return 0


if __name__ == "__main__":
    sys.exit(main())
