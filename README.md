# New-SP-Endpoints-notification

Watches [developer.scalepad.com](https://developer.scalepad.com) for documentation changes that the curated
[changelog](https://developer.scalepad.com/changelog) doesn't list — new or removed endpoints, changed
parameters, new response codes, deprecations, edited guides — and posts a daily summary to a Slack channel.

No ReadMe API key required. Everything comes from public URLs.

## How it works

1. **Index** — `GET /llms.txt`. ReadMe publishes this as an index of every page on the site
   (~6 guides + ~390 endpoint reference pages), one line each: title, URL, description.
2. **Detail** — every page is also available as markdown by appending `.md`. Endpoint pages carry an
   `updatedAt` timestamp and embed the endpoint's OpenAPI definition, so the script extracts the
   HTTP method, path, product (Core / Lifecycle Manager / ControlMap / Quoter / Backup Radar),
   parameters, request-body fields and response codes.
3. **Diff** — compared against `state/snapshot.json` from the previous run:
   - pages **added** / **removed** (new endpoint = new page)
   - pages **changed** (content hash differs), with a compact semantic explanation where possible:
     `params added: query:sort`, `responses added: 429`, `marked deprecated`, `request fields removed: …`
4. **Notify** — a Slack Block Kit message grouped by product is posted to `$SLACK_WEBHOOK_URL`.
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

Until the secret exists, runs still diff and commit the report — they just print the Slack payload
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

Stdlib only — Python 3.10+, no `pip install`.

## What a notification looks like

```
ScalePad Developer Docs — changes detected
Sep 10, 2026 15:00 UTC · tracking 396 pages · 3 added · 1 removed · 3 changed

🆕 New endpoints / pages (3)
  Lifecycle Manager API
  • POST /api/public/v1/agreements — Create Agreement
  Backup Radar API
  • POST /v1/backups/results — Ingest Backup Results
  Guides
  • API versioning policy

🗑️ Removed (1)
  ControlMap API
  • DELETE /v1/evidence/{id}/requests/{reqId} — Delete Evidence Request

✏️ Changed (3)
  Core API
  • GET /v1/clients — List Clients
      ◦ params added: `query:sort`
  Lifecycle Manager API
  • GET /api/public/v1/assessments — List Assessments
      ◦ responses added: `429`
      ◦ marked deprecated
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

- **Breaking-change classification** — pull the full OpenAPI specs via the ReadMe admin API and run
  [`oasdiff`](https://github.com/Tufin/oasdiff) for a formal breaking/non-breaking verdict.
- **Per-product channels** — route Core / LM / ControlMap / Quoter / Backup Radar to different webhooks.
- **Weekly digest** — change the cron and let the diff accumulate.
