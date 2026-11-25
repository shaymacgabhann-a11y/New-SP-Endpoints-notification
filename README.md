# New-SP-Endpoints-notification

Watches [developer.scalepad.com](https://developer.scalepad.com) for documentation changes that the curated
[changelog](https://developer.scalepad.com/changelog) doesn't list - new or removed endpoints, changed
parameters, retyped or newly required fields, new response codes, deprecations - and posts a daily summary to a Slack channel.

No ReadMe API key required. Everything comes from public URLs.

## How it works

1. **Index** - `GET /llms.txt`. ReadMe publishes this as an index of every page on the site
   (guides, changelog entries and ~900 endpoint reference pages), one line each: title, URL, description.
   Only the `/reference/` endpoint pages are tracked; guide and changelog pages are ignored.
2. **Detail** - every page is also available as markdown by appending `.md`. Endpoint pages carry an
   `updatedAt` timestamp and embed the endpoint's OpenAPI definition, so the script extracts the
   HTTP method, path, product (Core / Lifecycle Manager / ControlMap / Quoter / Backup Radar),
   parameters, request-body fields and response codes. For each endpoint it stores a field-level
   fingerprint: every parameter and every (nested) request / response field with its type, required,
   nullable, enum values, default, constraints and a hash of its description, plus the servers,
   API version, examples and the endpoint's description text.
3. **Diff** - compared against `state/snapshot.json` from the previous run:
   - pages **added** / **removed** (new endpoint = new page)
   - pages **changed** (content hash differs), explained field by field, e.g.
     `param added: query:sort`, `param query:page_size: constraints maximum=200 → maximum=500`,
     `200 response field added: data[].region`, `200 response field data[].status: enum values added archived`,
     `description: “…old text…” → “…new text…”`, `marked deprecated`
   - a change that shows up on many endpoints in one run (≥ 5, e.g. a new server URL across a whole API)
     is reported **once** under "Changes across many endpoints" instead of under every endpoint
   - pages whose markdown changed but whose spec and text didn't (formatting only) are not reported
4. **Notify** - a Slack Block Kit message grouped by product is posted to `$SLACK_WEBHOOK_URL`.
   The same content is written to `state/last_report.md` and committed, so the repo history is an
   audit log of every detected change.

Runs daily at 15:00 UTC (08:00 Pacific) via GitHub Actions, or on demand from the Actions tab.
The first run only establishes a baseline and posts nothing. If the site fetch is unreliable
(llms.txt empty, or >25 % of pages failing) the run aborts without touching the snapshot, so a
transient outage never produces a bogus "300 endpoints removed" message.

## Setup

### 1. Slack incoming webhook (placeholder until approved)

Ask a Slack admin to create an **Incoming Webhook** for the target channel
(Slack → Apps → *Incoming WebHooks* → Add to Slack → pick channel → copy the
`https://hooks.slack.com/services/T…/B…/…` URL).

Then in this repo: **Settings → Secrets and variables → Actions → New repository secret**

| Name                | Value                           |
|---------------------|---------------------------------|
| `SLACK_WEBHOOK_URL` | the `https://hooks.slack.com/…` URL |

Until the secret exists, runs still diff and commit the report - they just print the Slack payload
in the Actions log instead of posting. Nothing else needs to change once the URL is added.

### 2. Establish the baseline

Actions → **Check ScalePad developer docs** → *Run workflow*. The first run commits
`state/snapshot.json`; subsequent runs report against it.

## Running locally

```bash
python3 check_docs.py --dry-run          # diff against state/snapshot.json, print instead of post
python3 check_docs.py --no-save          # don't overwrite the snapshot
SLACK_WEBHOOK_URL=https://hooks.slack.com/... python3 check_docs.py   # post for real
python3 -m unittest -v tests/test_check_docs.py                        # tests (offline, fixture server)
```

Stdlib only - Python 3.10+, no `pip install`.

## What a notification looks like

```
ScalePad API endpoints: changes detected
Nov 25, 2026 15:00 UTC · tracking 902 endpoints · 1 added · 0 removed · 490 changed

🆕 New endpoints (1)
  Backup Radar API
  • POST /v1/backups/results - Ingest Backup Results

🌐 Changes across many endpoints (1)
  • servers added: `https://api.eu.scalepad.com (EU region)` - 488 endpoints (ScalePad CS API)

✏️ Endpoint-specific changes (2)
  ControlMap API
  • GET /controlmap/v1/clients/assessments/common/summary - Clients' Assessment Overview
      ◦ marked deprecated
      ◦ responses added: `429`
  Core API
  • GET /core/v1/clients - List Clients
      ◦ param added: `query:filter[region]`
      ◦ param `query:page_size`: constraints `minimum=1, maximum=200` → `minimum=1, maximum=500`
      ◦ `200` response field added: `data[].region`
      ◦ `200` response field description reworded: `data[].address`
      ◦ page text: “This endpoint retrieves a detailed list…” → “This endpoint retrieves a paginated, detailed list…”
```

## Repo layout

```
check_docs.py                 the whole thing (fetch → parse → diff → notify → snapshot)
.github/workflows/check-docs.yml
state/snapshot.json           last known state of every page (committed by the workflow)
state/last_report.md          most recent change report (committed by the workflow)
tests/                        offline end-to-end tests with fixture copies of the site
```

## Possible extensions

- **Breaking-change classification** - pull the full OpenAPI specs via the ReadMe admin API and run
  [`oasdiff`](https://github.com/Tufin/oasdiff) for a formal breaking/non-breaking verdict.
- **Per-product channels** - route Core / LM / ControlMap / Quoter / Backup Radar to different webhooks.
- **Weekly digest** - change the cron and let the diff accumulate.
