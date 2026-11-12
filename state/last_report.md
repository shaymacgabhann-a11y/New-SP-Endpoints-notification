# ScalePad developer docs — changes detected 2026-11-12 21:48 UTC

Tracking 792 pages at https://developer.scalepad.com. **3 added · 1 removed · 9 changed**

## Added (3)
### ControlMap API
- [PATCH /controlmap/v1/clients/{client_id}/frameworks/{framework_id}/objectives/bulk-update — Bulk Update Client Objective Notes](https://developer.scalepad.com/reference/bulkupdateclientobjectivenotes)
- [GET /controlmap/v1/clients/{client_id}/frameworks/{framework_id}/objectives/{objective_id}/notes — Get Client Objective Notes](https://developer.scalepad.com/reference/getclientobjectivenotes)

### Guides
- [ControlMap API - Objective notes and bulk updates](https://developer.scalepad.com/changelog/20261103-control-map-v1-changelog)

## Removed (1)
### Guides
- [Lifecycle Manager API - Agreement Budgets, Client Tags, and Meeting Details](https://developer.scalepad.com/changelog/20261103-lifecycle-manager-v1-changelog)

## Changed (9)
### ControlMap API
- [POST /controlmap/v1/clients/{client_id}/action-items — Create a new action item](https://developer.scalepad.com/reference/createactionitem-1)
  - page content updated (schema details / examples / prose)
- [GET /controlmap/v1/clients/{client_id}/frameworks/{framework_id}/objectives/{objective_id} — Get Client's Objective](https://developer.scalepad.com/reference/02_getclientobjectivebyid)
  - page content updated (schema details / examples / prose)
- [PATCH /controlmap/v1/clients/{client_id}/frameworks/{framework_id}/objectives/{objective_id} — Partially Update Client's Objective](https://developer.scalepad.com/reference/05_updateclientobjective)
  - request fields added: `sub_objectives`

### Guides
- [API versioning policy](https://developer.scalepad.com/docs/api-versioning-policy)
  - page content updated (schema details / examples / prose)
- [Getting started with the ScalePad API](https://developer.scalepad.com/docs/getting-started)
  - page content updated (schema details / examples / prose)
- [Product APIs and subscriptions](https://developer.scalepad.com/docs/product-apis-and-subscriptions)
  - page content updated (schema details / examples / prose)
- [Regional endpoints and compliance](https://developer.scalepad.com/docs/regional-endpoints-and-compliance)
  - page content updated (schema details / examples / prose)
- [ScalePad MCP](https://developer.scalepad.com/docs/mcp)
  - page content updated (schema details / examples / prose)
- [ScalePad x Zapier](https://developer.scalepad.com/docs/zapier-integration)
  - page content updated (schema details / examples / prose)
