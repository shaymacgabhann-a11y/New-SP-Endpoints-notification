# ScalePad developer docs — changes detected 2026-11-18 22:32 UTC

Tracking 802 pages at https://developer.scalepad.com. **2 added · 0 removed · 23 changed**

## Added (2)
### ControlMap API
- [GET /controlmap/v1/clients/{client_id}/objectives/{objective_id} — Get Client Objective](https://developer.scalepad.com/reference/04_getclientobjectivebyid)
- [PATCH /controlmap/v1/clients/{client_id}/objectives/{objective_id} — Partially Update Client Objective](https://developer.scalepad.com/reference/06_updateclientobjectivebyid)

## Changed (23)
### ControlMap API
- [GET /controlmap/v1/clients/{client_id}/action-items/{action_item_id} — Get Action Item](https://developer.scalepad.com/reference/b_actionitem-1)
  - page content updated (schema details / examples / prose)
- [POST /controlmap/v1/clients/{client_id}/controls — Create Control](https://developer.scalepad.com/reference/opencontrolscreate)
  - request fields added: `mappings`
- [POST /controlmap/v1/clients/{client_id}/controls/{control_id}/mappings — Map Policy, Procedure, Governance, Risk, Evidence, and Action Items to Control](https://developer.scalepad.com/reference/opencontrolsmapmappings)
  - request fields added: `objective_ids`
- [POST /controlmap/v1/clients/{client_id}/controls/{control_id}/mappings/bulk-delete — Unmap Policy, Procedure, Governance, Risk, Evidence, and Action Items from Control](https://developer.scalepad.com/reference/opencontrolsbulkdeletemappings)
  - request fields added: `objective_ids`
- [POST /controlmap/v1/clients/{client_id}/evidences — Create Client's Evidence](https://developer.scalepad.com/reference/03_evidenceapi-1)
  - page content updated (schema details / examples / prose)
- [POST /controlmap/v1/clients/{client_id}/evidences/{evidence_id}/mappings — Map Evidence to Objectives or Controls](https://developer.scalepad.com/reference/evidencemapentitiesforclient)
  - request fields added: `objective_ids`
- [POST /controlmap/v1/clients/{client_id}/evidences/{evidence_id}/mappings/bulk-delete — Unmap Evidence from Objectives or Controls](https://developer.scalepad.com/reference/evidenceunmapentitiesforclient)
  - request fields added: `objective_ids`
- [GET /controlmap/v1/clients/{client_id}/frameworks/{framework_id}/objectives/{objective_id} — Get Client's Objective](https://developer.scalepad.com/reference/02_getclientobjectivebyid)
  - description text updated
- [PATCH /controlmap/v1/clients/{client_id}/frameworks/{framework_id}/objectives/{objective_id} — Partially Update Client's Objective](https://developer.scalepad.com/reference/05_updateclientobjective)
  - page content updated (schema details / examples / prose)
- [POST /controlmap/v1/clients/{client_id}/governance — Create Client's Governance](https://developer.scalepad.com/reference/createclientgovernancedocument)
  - request fields added: `mappings`
- [POST /controlmap/v1/clients/{client_id}/governance/{governance_id}/mappings — Map Governance to Objectives, Policies, and Controls](https://developer.scalepad.com/reference/mapentitiestoclientgovernancedocument)
  - request fields added: `objective_ids`
- [POST /controlmap/v1/clients/{client_id}/governance/{governance_id}/mappings/bulk-delete — Unmap Governance from Objectives, Policies, and Controls](https://developer.scalepad.com/reference/bulkdeleteentitiesfromclientgovernance)
  - request fields added: `objective_ids`
- [POST /controlmap/v1/clients/{client_id}/procedures — Create Client's Procedure](https://developer.scalepad.com/reference/createclientprocedure)
  - request fields added: `mappings`
- [POST /controlmap/v1/clients/{client_id}/procedures/{procedure_id}/mappings — Map Procedure to Objectives, Policies, and Controls](https://developer.scalepad.com/reference/mapentitiestoclientprocedure)
  - request fields added: `objective_ids`
- [POST /controlmap/v1/clients/{client_id}/procedures/{procedure_id}/mappings/bulk-delete — Unmap Procedure from Objectives, Policies, and Controls](https://developer.scalepad.com/reference/bulkdeleteentitiesfromclientprocedure)
  - request fields added: `objective_ids`
- [POST /controlmap/v1/clients/{client_id}/risks/{risk_id}/mappings — Map Risk to Assets, Asset Types, Threats, Vulnerabilities, or Vendors](https://developer.scalepad.com/reference/mapentitiestoclientrisk)
  - request fields added: `objective_ids`
- [POST /controlmap/v1/clients/{client_id}/risks/{risk_id}/mappings/bulk-delete — Unmap Risk from Assets, Asset Types, Threats, Vulnerabilities, or Vendors](https://developer.scalepad.com/reference/bulkdeleteentitiesfromclientrisk)
  - request fields added: `objective_ids`

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
