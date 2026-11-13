# ScalePad developer docs — changes detected 2026-11-13 21:22 UTC

Tracking 800 pages at https://developer.scalepad.com. **9 added · 1 removed · 8 changed**

## Added (9)
### ControlMap API
- [GET /controlmap/v1/clients/{client_id}/frameworks/{framework_id}/objective-responses — List Objective Responses](https://developer.scalepad.com/reference/listclientobjectiveresponses)
- [DELETE /controlmap/v1/clients/{client_id}/frameworks/{framework_id}/objectives/{objective_id}/raci/{person_id} — Clear Objective Responsibility](https://developer.scalepad.com/reference/clearclientobjectiveresponsibility)
- [PATCH /controlmap/v1/clients/{client_id}/frameworks/{framework_id}/objectives/{objective_id}/raci/{person_id} — Update Objective Responsibility](https://developer.scalepad.com/reference/updateclientobjectiveresponsibility)
- [PATCH /controlmap/v1/clients/{client_id}/frameworks/{framework_id}/objectives/{objective_id}/sub-objectives/{sub_objective_id} — Update Client Sub-objective](https://developer.scalepad.com/reference/updateclientsubobjective)
- [DELETE /controlmap/v1/clients/{client_id}/frameworks/{framework_id}/objectives/{objective_id}/sub-objectives/{sub_objective_id}/raci/{person_id} — Clear Sub-objective Responsibility](https://developer.scalepad.com/reference/clearclientsubobjectiveresponsibility)
- [PATCH /controlmap/v1/clients/{client_id}/frameworks/{framework_id}/objectives/{objective_id}/sub-objectives/{sub_objective_id}/raci/{person_id} — Update Sub-objective Responsibility](https://developer.scalepad.com/reference/updateclientsubobjectiveresponsibility)
- [DELETE /controlmap/v1/clients/{client_id}/frameworks/{framework_id}/raci/{person_id}/responsibilities — Clear Framework Responsibilities](https://developer.scalepad.com/reference/clearclientframeworkresponsibilities)
- [PATCH /controlmap/v1/clients/{client_id}/frameworks/{framework_id}/raci/{person_id}/responsibilities — Update Framework Responsibilities](https://developer.scalepad.com/reference/updateclientframeworkresponsibilities)

### Guides
- [ControlMap API - Sub-objective answers and RACI updates](https://developer.scalepad.com/changelog/20261113-control-map-v1-changelog)

## Removed (1)
### Guides
- [Canonical Lifecycle Manager API paths](https://developer.scalepad.com/changelog/20261104-lifecycle-manager-v1-changelog)

## Changed (8)
### ControlMap API
- [GET /controlmap/v1/clients/{client_id}/frameworks/{framework_id}/objectives/{objective_id} — Get Client's Objective](https://developer.scalepad.com/reference/02_getclientobjectivebyid)
  - page content updated (schema details / examples / prose)
- [PATCH /controlmap/v1/clients/{client_id}/frameworks/{framework_id}/objectives/{objective_id} — Partially Update Client's Objective](https://developer.scalepad.com/reference/05_updateclientobjective)
  - page content updated (schema details / examples / prose)

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
