---
updatedAt: 2026-04-23T21:49:21.000Z
---

Fetch the complete documentation index at: https://developer.scalepad.com/llms.txt. Use this file to discover all available pages before exploring further. Append .md to any documentation page URL to get its markdown version.

# Delete Evidence Request

Deletes a specific evidence request.

# OpenAPI definition

```json
{
  "openapi": "3.0.1",
  "info": {
    "title": "ControlMap API",
    "version": "v1"
  },
  "servers": [
    {
      "url": "https://api.scalepad.com"
    }
  ],
  "paths": {
    "/v1/evidence/{id}/requests/{reqId}": {
      "delete": {
        "summary": "Delete Evidence Request",
        "parameters": [],
        "responses": {
          "204": {
            "description": "x"
          }
        }
      }
    }
  },
  "components": {
    "schemas": {
      "Body": {
        "type": "object",
        "properties": {}
      }
    }
  }
}
```
