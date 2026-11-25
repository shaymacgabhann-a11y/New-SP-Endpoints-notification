#!/usr/bin/env python3
"""
Watch developer.scalepad.com for documentation changes and report them to Slack.

How it works
------------
1. Fetch https://developer.scalepad.com/llms.txt - ReadMe's index of every published
   page (guides + one page per API endpoint).
2. Fetch each page's markdown (`<url>.md`). Endpoint pages carry an `updatedAt`
   frontmatter field and embed the endpoint's OpenAPI definition, so we can extract
   HTTP method, path, product, parameters, request fields and response codes.
3. Compare against the previous snapshot (state/snapshot.json) and report:
     - endpoints added / removed
     - endpoints changed, with a field-level explanation (parameter / request /
       response field added, removed, retyped, made required, enum values,
       defaults, description edits, servers, API version, examples …)
     - changes shared by many endpoints at once (e.g. a new server URL on every
       endpoint of one API) are collapsed into a single "across N endpoints" line
   Guide and changelog pages (/docs/, /changelog/) are ignored: only /reference/
   endpoint pages are tracked.
4. Post a Slack Block Kit message to $SLACK_WEBHOOK_URL (if set) and write
   state/last_report.md. Then save the new snapshot.

The first run establishes a baseline and posts nothing.

Stdlib only - no third-party dependencies.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import difflib
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
MAX_DETAILS_PER_PAGE_SLACK = 6

# Page kinds that are tracked. Guides / changelog pages change constantly and are noise.
TRACKED_KINDS = {"endpoint"}

# A detail line that appears on at least this many endpoints in one run is reported
# once in an "across N endpoints" section rather than repeated under every endpoint.
SHARED_CHANGE_MIN = 5

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
    fingerprint: dict[str, Any] = field(default_factory=dict)  # field-level detail, see build_fingerprint
    fetch_error: str | None = None

    @property
    def label(self) -> str:
        if self.method and self.path:
            return f"`{self.method} {self.path}` - {self.title}"
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


def _h(obj: Any) -> str:
    if not isinstance(obj, str):
        obj = json.dumps(obj, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(obj.encode()).hexdigest()[:10]


def _norm_text(s: Any) -> str:
    return re.sub(r"\s+", " ", s if isinstance(s, str) else "").strip()


def _deref(spec: dict, obj: Any) -> tuple[Any, frozenset[str]]:
    """Resolve a $ref chain, keeping sibling keys (e.g. a description next to a $ref).
    Returns the resolved node and the set of refs followed (for cycle detection)."""
    refs: set[str] = set()
    overlay: dict = {}
    for _ in range(10):
        if not isinstance(obj, dict) or "$ref" not in obj:
            break
        ref = obj["$ref"]
        overlay = {**{k: v for k, v in obj.items() if k != "$ref"}, **overlay}
        if not isinstance(ref, str) or not ref.startswith("#/") or ref in refs:
            break
        refs.add(ref)
        node: Any = spec
        for part in ref[2:].split("/"):
            node = node.get(part) if isinstance(node, dict) else None
        if node is None:
            break
        obj = node
    if overlay and isinstance(obj, dict):
        obj = {**obj, **overlay}
    return obj, frozenset(refs)


_CONSTRAINT_KEYS = ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "minLength",
                    "maxLength", "pattern", "minItems", "maxItems", "uniqueItems", "multipleOf")


def _schema_sig(schema: Any, required: bool, description: Any = None) -> dict[str, Any]:
    """Compact, diffable signature of one parameter / field. Falsy attributes are omitted."""
    schema = schema if isinstance(schema, dict) else {}
    sig: dict[str, Any] = {}
    t = schema.get("type")
    if isinstance(t, list):
        t = "|".join(str(x) for x in t)
    if not t:
        for combo in ("oneOf", "anyOf", "allOf"):
            if schema.get(combo):
                t = combo
                break
    if t:
        sig["t"] = t
    if schema.get("format"):
        sig["f"] = schema["format"]
    if required:
        sig["req"] = 1
    if schema.get("nullable"):
        sig["null"] = 1
    if isinstance(schema.get("enum"), list):
        sig["enum"] = [str(x) for x in schema["enum"]]
    if "default" in schema:
        sig["def"] = json.dumps(schema["default"], ensure_ascii=False)
    if schema.get("deprecated"):
        sig["dep"] = 1
    if schema.get("readOnly"):
        sig["ro"] = 1
    cons = [f"{k}={json.dumps(schema[k])}" for k in _CONSTRAINT_KEYS if k in schema]
    if cons:
        sig["c"] = ", ".join(cons)
    desc = _norm_text(description if description is not None else schema.get("description"))
    if desc:
        sig["d"] = _h(desc)
    return sig


MAX_FIELDS_PER_SCHEMA = 600


def _walk_fields(spec: dict, schema: Any, prefix: str, out: dict, stack: frozenset = frozenset(),
                 depth: int = 0) -> None:
    """Record a signature for every property reachable from `schema`, keyed by a dotted
    path (`data[].address.city`). Arrays add `[]`, maps add `{}`."""
    schema, refs = _deref(spec, schema)
    if not isinstance(schema, dict) or depth > 12 or (refs & stack) or len(out) > MAX_FIELDS_PER_SCHEMA:
        return
    stack = stack | refs
    required = set(schema.get("required") or [])
    for name, sub in (schema.get("properties") or {}).items():
        path = f"{prefix}.{name}" if prefix else name
        rsub, _ = _deref(spec, sub)
        out[path] = _schema_sig(rsub, name in required)
        _walk_fields(spec, sub, path, out, stack, depth + 1)
    for combo in ("allOf", "oneOf", "anyOf"):
        for sub in schema.get(combo) or []:
            _walk_fields(spec, sub, prefix, out, stack, depth + 1)
    if "items" in schema:
        _walk_fields(spec, schema["items"], prefix + "[]", out, stack, depth + 1)
    if isinstance(schema.get("additionalProperties"), dict):
        _walk_fields(spec, schema["additionalProperties"], prefix + "{}", out, stack, depth + 1)


def _collect_examples(node: Any, out: list) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            if k in ("example", "examples", "x-readme-examples"):
                out.append(v)
            else:
                _collect_examples(v, out)
    elif isinstance(node, list):
        for v in node:
            _collect_examples(v, out)


def build_fingerprint(spec: dict, path: str, method: str, op: dict, prose: str) -> dict[str, Any]:
    """Everything we need to explain *what* changed on an endpoint page next run."""
    path_item = (spec.get("paths") or {}).get(path) or {}
    params: dict[str, dict] = {}
    for p in list(path_item.get("parameters") or []) + list(op.get("parameters") or []):
        p, _ = _deref(spec, p)
        if not isinstance(p, dict) or "name" not in p:
            continue
        sch, _ = _deref(spec, p.get("schema") or {})
        sig = _schema_sig(sch, bool(p.get("required")), p.get("description") or (sch or {}).get("description"))
        if p.get("deprecated"):
            sig["dep"] = 1
        params[f"{p.get('in', '?')}:{p['name']}"] = sig

    request: dict[str, dict] = {}
    rb, _ = _deref(spec, op.get("requestBody"))
    if isinstance(rb, dict):
        for media in (rb.get("content") or {}).values():
            if isinstance(media, dict):
                _walk_fields(spec, media.get("schema"), "", request)

    responses: dict[str, dict] = {}
    for code, r in (op.get("responses") or {}).items():
        r, _ = _deref(spec, r)
        if not isinstance(r, dict):
            continue
        fields: dict[str, dict] = {}
        for media in (r.get("content") or {}).values():
            if isinstance(media, dict):
                _walk_fields(spec, media.get("schema"), "", fields)
        responses[str(code)] = {"d": _h(_norm_text(r.get("description"))), "fields": fields}

    info = spec.get("info") or {}
    examples: list = []
    _collect_examples(spec, examples)
    components = spec.get("components") or {}
    sections = {
        "info": _h(info),
        "servers": _h(spec.get("servers") or []),
        "tags": _h(spec.get("tags") or []),
        "security": _h([components.get("securitySchemes"), spec.get("security"), op.get("security")]),
        "operation": _h(op),
    }
    for name, sch in (components.get("schemas") or {}).items():
        sections[f"schema {name.rsplit('.', 1)[-1]}"] = _h(sch)
    servers = []
    for s in spec.get("servers") or []:
        if isinstance(s, dict) and s.get("url"):
            servers.append(s["url"] + (f" ({_norm_text(s['description'])})" if s.get("description") else ""))
    description = _norm_text(op.get("description"))[:4000]
    prose = _norm_text(prose)[:4000]
    return {
        "summary": _norm_text(op.get("summary")),
        "description": description,
        "prose": "" if prose == description else prose,  # usually identical; don't store twice
        "api_version": str(info.get("version") or ""),
        "info_description": _h(_norm_text(info.get("description"))),
        "servers": sorted(servers),
        "params": params,
        "request": request,
        "responses": responses,
        "examples": _h(examples) if examples else "",
        "sections": sections,
        "spec": _h(spec),
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
    # Human-written text on the page, minus the title heading and the embedded spec.
    prose = OPENAPI_BLOCK_RE.sub("", body)
    prose = re.sub(r"^#\s+.*$", "", prose, count=1, flags=re.M)
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
                page.fingerprint = build_fingerprint(spec, path, method, op, prose)
                return  # one operation per page


def carry_forward_failed(pages: list[Page], old_pages: dict[str, Page]) -> int:
    """Replace any page that failed to fetch this run with its last known-good
    record from the previous snapshot, in place. Returns how many were carried.

    A page that failed to fetch must not overwrite its last known-good record -
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
    # (detail, pages) for detail lines shared by many endpoints; those lines are
    # removed from the matching Change.details so they're only reported once.
    shared: list[tuple[str, list[Page]]] = field(default_factory=list)
    cosmetic: int = 0  # pages whose markdown changed but nothing meaningful did

    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.changed)


def _names(items: list[str], limit: int = 6) -> str:
    shown = ", ".join(f"`{x}`" for x in items[:limit])
    return shown + (f" +{len(items) - limit} more" if len(items) > limit else "")


def _set_delta(label: str, old: list[str], new: list[str]) -> list[str]:
    o, n = set(old), set(new)
    out = []
    if n - o:
        out.append(f"{label} added: " + _names(sorted(n - o)))
    if o - n:
        out.append(f"{label} removed: " + _names(sorted(o - n)))
    return out


def _clip(text: str, limit: int = 90) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def text_change(old: str, new: str, context: int = 4) -> str | None:
    """Show the first edited passage of a text as `“…old…” → “…new…”`."""
    a, b = old.split(), new.split()
    ops = [o for o in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes() if o[0] != "equal"]
    if not ops:
        return None
    _, i1, i2, j1, j2 = ops[0]

    def snippet(words: list[str], s: int, e: int) -> str:
        parts = words[max(0, s - context):e + context]
        return _clip(("…" if s > context else "") + " ".join(parts) + ("…" if e + context < len(words) else ""))

    was, now = snippet(a, i1, i2), snippet(b, j1, j2)
    more = f" (+{len(ops) - 1} more edit{'s' if len(ops) > 2 else ''})" if len(ops) > 1 else ""
    return f"“{was}” → “{now}”{more}"


def _type_str(sig: dict) -> str:
    t = sig.get("t") or "any"
    return f"{t}({sig['f']})" if sig.get("f") else t


def _sig_changes(o: dict, n: dict) -> list[str]:
    out: list[str] = []
    if (o.get("t"), o.get("f")) != (n.get("t"), n.get("f")):
        out.append(f"type `{_type_str(o)}` → `{_type_str(n)}`")
    if bool(o.get("req")) != bool(n.get("req")):
        out.append("now required" if n.get("req") else "now optional")
    if bool(o.get("null")) != bool(n.get("null")):
        out.append("now nullable" if n.get("null") else "no longer nullable")
    if o.get("enum") != n.get("enum"):
        oe, ne = o.get("enum") or [], n.get("enum") or []
        if not oe:
            out.append("now restricted to " + _names(ne))
        elif not ne:
            out.append("no longer an enum")
        else:
            if set(ne) - set(oe):
                out.append("enum values added " + _names([x for x in ne if x not in oe]))
            if set(oe) - set(ne):
                out.append("enum values removed " + _names([x for x in oe if x not in ne]))
    if o.get("def") != n.get("def"):
        out.append(f"default `{o.get('def', 'none')}` → `{n.get('def', 'none')}`")
    if bool(o.get("dep")) != bool(n.get("dep")):
        out.append("marked *deprecated*" if n.get("dep") else "no longer deprecated")
    if bool(o.get("ro")) != bool(n.get("ro")):
        out.append("now read-only" if n.get("ro") else "no longer read-only")
    if o.get("c") != n.get("c"):
        out.append(f"constraints `{o.get('c') or 'none'}` → `{n.get('c') or 'none'}`")
    if o.get("d") != n.get("d"):
        out.append("description reworded" if o.get("d") and n.get("d")
                   else "description added" if n.get("d") else "description removed")
    return out


def _collapse_nested(paths: list[str]) -> tuple[list[str], int]:
    """Keep only top-most paths: if `address` was added, don't also list `address.city`."""
    s = set(paths)
    top = [p for p in sorted(paths)
           if not any(p != q and (p.startswith(q + ".") or p.startswith(q + "[]") or p.startswith(q + "{}"))
                      for q in s)]
    return top, len(paths) - len(top)


def _field_map_delta(label: str, old: dict, new: dict) -> list[str]:
    """Describe added / removed / changed entries between two {name: sig} maps."""
    d: list[str] = []
    added, nested_a = _collapse_nested([k for k in new if k not in old])
    removed, nested_r = _collapse_nested([k for k in old if k not in new])
    if added:
        d.append(f"{label} added: {_names(added)}" + (f" (+{nested_a} nested)" if nested_a else ""))
    if removed:
        d.append(f"{label} removed: {_names(removed)}" + (f" (+{nested_r} nested)" if nested_r else ""))
    reworded: list[str] = []
    for k in sorted(set(old) & set(new)):
        ch = _sig_changes(old[k], new[k])
        if ch == ["description reworded"]:
            reworded.append(k)
        elif ch:
            d.append(f"{label} `{k}`: " + ", ".join(ch))
    if reworded:
        d.append(f"{label} description reworded: {_names(reworded)}")
    return d


def _fingerprint_delta(of: dict, nf: dict) -> list[str]:
    d: list[str] = []
    d += _field_map_delta("param", of.get("params", {}), nf.get("params", {}))
    d += _field_map_delta("request field", of.get("request", {}), nf.get("request", {}))

    ores, nres = of.get("responses", {}), nf.get("responses", {})
    d += _set_delta("responses", list(ores), list(nres))
    for code in sorted(set(ores) & set(nres)):
        d += _field_map_delta(f"`{code}` response field", ores[code].get("fields", {}), nres[code].get("fields", {}))
        if ores[code].get("d") != nres[code].get("d"):
            d.append(f"`{code}` response description reworded")

    if of.get("summary") != nf.get("summary"):
        d.append(f"summary: “{_clip(of.get('summary', ''), 60)}” → “{_clip(nf.get('summary', ''), 60)}”")
    desc = text_change(of.get("description", ""), nf.get("description", ""))
    if desc:
        d.append("description: " + desc)
    else:
        # An empty "prose" means "same as the description" (see build_fingerprint).
        prose = text_change(of.get("prose") or of.get("description", ""), nf.get("prose") or nf.get("description", ""))
        if prose:
            d.append("page text: " + prose)
    if of.get("examples") != nf.get("examples"):
        d.append("request/response examples updated")
    d += _set_delta("servers", of.get("servers", []), nf.get("servers", []))
    if of.get("api_version") != nf.get("api_version"):
        d.append(f"API version `{of.get('api_version')}` → `{nf.get('api_version')}`")
    if of.get("info_description") != nf.get("info_description"):
        d.append("API overview text (OpenAPI `info.description`) reworded")
    osec, nsec = of.get("sections", {}), nf.get("sections", {})
    if osec.get("security") != nsec.get("security"):
        d.append("authentication / security definition changed")

    if not d and of.get("spec") != nf.get("spec"):
        # Something changed in the spec that we don't model field-by-field: at least say where.
        where = sorted(k for k in set(osec) | set(nsec) if osec.get(k) != nsec.get(k))
        if where:
            d.append("other OpenAPI changes in " + _names(where, 4))
        else:
            d.append("other OpenAPI changes (not field-level)")
    return d


def describe_change(old: Page, new: Page) -> list[str]:
    """Explain what changed. Returns [] when nothing meaningful did (formatting only)."""
    d: list[str] = []
    if old.method != new.method or old.path != new.path:
        d.append(f"route changed: `{old.method} {old.path}` → `{new.method} {new.path}`")
    if old.title != new.title:
        d.append(f"title: “{old.title}” → “{new.title}”")
    oo, no = old.operation or {}, new.operation or {}
    if oo.get("deprecated") != no.get("deprecated"):
        d.append("marked *deprecated*" if no.get("deprecated") else "no longer deprecated")

    if old.fingerprint and new.fingerprint:
        d += _fingerprint_delta(old.fingerprint, new.fingerprint)
        if old.description != new.description and not any(x.startswith(("description: ", "page text: ")) for x in d):
            d.append("index description (llms.txt) reworded")
        return d

    # Older snapshot without field-level data: fall back to name-level comparison.
    d += _set_delta("params", oo.get("parameters", []), no.get("parameters", []))
    d += _set_delta("request fields", oo.get("request_fields", []), no.get("request_fields", []))
    d += _set_delta("responses", oo.get("responses", []), no.get("responses", []))
    if not d:
        if old.description != new.description or oo.get("summary") != no.get("summary"):
            d.append("description text updated")
        else:
            d.append("page content updated (no field-level detail stored for the previous version yet)")
    return d


def extract_shared(changed: list[Change], min_count: int = SHARED_CHANGE_MIN) -> list[tuple[str, list[Page]]]:
    """Pull out detail lines that appear on many endpoints (API-wide changes, e.g. a new
    server URL or a reworded shared error schema) so they're reported once, not N times.
    Mutates `changed`: shared lines are removed from each Change.details."""
    counts: dict[str, list[Page]] = {}
    for c in changed:
        for det in dict.fromkeys(c.details):
            counts.setdefault(det, []).append(c.page)
    shared = {det: pages for det, pages in counts.items() if len(pages) >= min_count}
    for c in changed:
        c.details = [det for det in c.details if det not in shared]
    return sorted(shared.items(), key=lambda kv: (-len(kv[1]), kv[0]))


def compute_diff(old_pages: dict[str, Page], new_pages: list[Page]) -> Diff:
    new_by_key = {p.key: p for p in new_pages}
    added = [p for k, p in new_by_key.items() if k not in old_pages]
    removed = [p for k, p in old_pages.items() if k not in new_by_key]
    changed: list[Change] = []
    cosmetic = 0
    for k, new in new_by_key.items():
        old = old_pages.get(k)
        if not old or new.fetch_error or old.fetch_error:
            continue  # don't report a change we can't verify
        if old.content_hash != new.content_hash:
            details = describe_change(old, new)
            if details:
                changed.append(Change(new, details))
            else:
                cosmetic += 1

    def sort_key(p: Page):
        return (p.kind != "endpoint", p.product or "", p.path or "", p.method or "", p.title)

    added.sort(key=sort_key)
    removed.sort(key=sort_key)
    changed.sort(key=lambda c: sort_key(c.page))
    shared = extract_shared(changed)
    return Diff(added, removed, changed, shared, cosmetic)


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #

def _group_by_product(pages: list[Page]) -> dict[str, list[Page]]:
    groups: dict[str, list[Page]] = {}
    for p in pages:
        groups.setdefault(p.product or ("Guides" if p.kind == "guide" else "Other"), []).append(p)
    return dict(sorted(groups.items()))


def _product_counts(pages: list[Page]) -> str:
    counts: dict[str, int] = {}
    for p in pages:
        name = p.product or "Other"
        counts[name] = counts.get(name, 0) + 1
    return ", ".join(f"{name} ×{n}" if len(counts) > 1 else name
                     for name, n in sorted(counts.items(), key=lambda kv: -kv[1]))


def _specific_changes(diff: Diff) -> list[Change]:
    """Changed endpoints that still have something to say after shared lines were pulled out."""
    return [c for c in diff.changed if c.details]


def render_markdown(diff: Diff, total: int, base_url: str, now: datetime) -> str:
    lines = [f"# ScalePad developer docs: changes detected {now:%Y-%m-%d %H:%M UTC}", ""]
    lines.append(f"Tracking {total} endpoints at {base_url}. "
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
    if diff.shared:
        lines.append(f"## Changes across many endpoints ({len(diff.shared)})")
        for det, pages in diff.shared:
            lines.append(f"- {det} - **{len(pages)} endpoints** ({_product_counts(pages)})")
        lines.append("")
    specific = _specific_changes(diff)
    section("Endpoint-specific changes" if diff.shared else "Changed", [c.page for c in specific], {c.page.key: c.details for c in specific})
    return "\n".join(lines).rstrip() + "\n"


def _slack_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _md_link(p: Page) -> str:
    text = f"{p.method} {p.path}" if p.method and p.path else p.title
    return f"<{p.url}|{_slack_escape(text)}>" + (f" - {_slack_escape(p.title)}" if p.method else "")


def build_slack_payload(diff: Diff, total: int, base_url: str, now: datetime) -> dict:
    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": "ScalePad API endpoints: changes detected", "emoji": True}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text":
            f"{now:%b %d, %Y %H:%M UTC} · tracking {total} endpoints · "
            f"*{len(diff.added)} added* · *{len(diff.removed)} removed* · *{len(diff.changed)} changed*"}]},
        {"type": "divider"},
    ]

    def add_text_blocks(text_lines: list[str]) -> None:
        text = "\n".join(text_lines)
        if len(text) > 2900:
            text = text[:2850] + "\n…"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text}})

    def add_section(emoji: str, title: str, pages: list[Page], details: dict[str, list[str]] | None = None):
        if not pages:
            return
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"{emoji} *{title}* ({len(pages)})"}})
        shown = 0
        for product, group in _group_by_product(pages).items():
            if shown >= MAX_ITEMS_PER_SECTION or len(blocks) >= MAX_BLOCKS - 3:
                break
            text_lines = [f"*{product}*"]
            for p in group:
                if shown >= MAX_ITEMS_PER_SECTION:
                    break
                text_lines.append(f"• {_md_link(p)}")
                page_details = (details or {}).get(p.key, [])
                for d in page_details[:MAX_DETAILS_PER_PAGE_SLACK]:
                    text_lines.append(f"      ◦ {_slack_escape(d)}")
                if len(page_details) > MAX_DETAILS_PER_PAGE_SLACK:
                    text_lines.append(f"      ◦ _+{len(page_details) - MAX_DETAILS_PER_PAGE_SLACK} more in the full report_")
                shown += 1
            add_text_blocks(text_lines)
        remaining = len(pages) - shown
        if remaining > 0:
            blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"…and {remaining} more - see the full report in the repo."}]})

    add_section(":new:", "New endpoints", diff.added)
    add_section(":wastebasket:", "Removed endpoints", diff.removed)
    if diff.shared:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text":
            f":globe_with_meridians: *Changes across many endpoints* ({len(diff.shared)})"}})
        shared_lines = [f"• {_slack_escape(det)} - *{len(pages)} endpoints* ({_slack_escape(_product_counts(pages))})"
                        for det, pages in diff.shared[:MAX_ITEMS_PER_SECTION]]
        add_text_blocks(shared_lines)
        if len(diff.shared) > MAX_ITEMS_PER_SECTION:
            blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text":
                f"…and {len(diff.shared) - MAX_ITEMS_PER_SECTION} more - see the full report in the repo."}]})
    specific = _specific_changes(diff)
    add_section(":pencil2:", "Endpoint-specific changes" if diff.shared else "Changed endpoints", [c.page for c in specific],
                {c.page.key: c.details for c in specific})

    blocks.append({"type": "divider"})
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text":
        f"Source: <{base_url}/llms.txt|llms.txt> · <{base_url}/changelog|Changelog> · "
        f"<https://github.com/shaymacgabhann-a11y/New-SP-Endpoints-notification|watcher repo>"}]})

    summary = (f"ScalePad API: {len(diff.added)} added, {len(diff.removed)} removed, "
               f"{len(diff.changed)} changed")
    if len(blocks) > 50:
        blocks = blocks[:48] + blocks[-2:]
    return {"text": summary, "blocks": blocks}


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
    """One compact JSON line per page: keeps the file small and git diffs one line per changed page."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [json.dumps(asdict(p), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            for p in sorted(pages, key=lambda p: p.key)]
    path.write_text('{"meta": ' + json.dumps(meta, sort_keys=True) + ',\n"pages": [\n' + ",\n".join(rows) + "\n]}\n")


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
        log("error: llms.txt parsed to zero pages - aborting without touching the snapshot")
        return 2
    listed = len(pages)
    pages = [p for p in pages if p.kind in TRACKED_KINDS]
    log(f"{listed} pages listed, {len(pages)} endpoint pages tracked; fetching markdown…")
    fetch_pages(pages, args.concurrency, log)

    failed = sum(1 for p in pages if p.fetch_error)
    if failed > len(pages) * 0.25:
        log(f"error: {failed}/{len(pages)} pages failed to fetch - treating run as unreliable, snapshot untouched")
        return 3

    old_pages, old_meta = load_snapshot(args.snapshot)
    # Older snapshots also held guide/changelog pages; drop them so they don't show as "removed".
    old_pages = {k: p for k, p in old_pages.items() if p.kind in TRACKED_KINDS}
    meta = {"base_url": base_url, "checked_at": now.isoformat(), "page_count": len(pages),
            "previous_checked_at": old_meta.get("checked_at")}

    carried = carry_forward_failed(pages, old_pages)
    if carried:
        log(f"carried forward last known-good data for {carried} page(s) that failed to fetch this run")

    if not old_pages:
        log("no previous snapshot - baseline established, nothing to report")
        if not args.no_save:
            save_snapshot(args.snapshot, pages, meta)
        return 0

    diff = compute_diff(old_pages, pages)
    if diff.cosmetic:
        log(f"ignored {diff.cosmetic} page(s) whose markdown changed but whose spec and text did not")
    if diff.is_empty():
        log("no changes")
        if not args.no_save:
            save_snapshot(args.snapshot, pages, meta)
        return 0

    log(f"changes: +{len(diff.added)} -{len(diff.removed)} ~{len(diff.changed)} "
        f"({len(diff.shared)} shared across many endpoints)")
    report = render_markdown(diff, len(pages), base_url, now)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report)
    print(report)

    payload = build_slack_payload(diff, len(pages), base_url, now)
    webhook = args.webhook.strip()
    if args.dry_run or not webhook or "hooks.slack.com" not in webhook:
        if not args.dry_run:
            log("SLACK_WEBHOOK_URL not set (or placeholder) - printing payload instead of posting")
        print(json.dumps(payload, indent=2))
    else:
        post_to_slack(webhook, payload)
        log("posted to Slack")

    if not args.no_save:
        save_snapshot(args.snapshot, pages, meta)
    return 0


if __name__ == "__main__":
    sys.exit(main())
