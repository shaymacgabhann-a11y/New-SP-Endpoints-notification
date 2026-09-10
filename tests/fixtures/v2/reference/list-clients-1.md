---
updatedAt: 2026-09-08T10:00:00.000Z
---

Fetch the complete documentation index at: https://developer.scalepad.com/llms.txt. Use this file to discover all available pages before exploring further. Append .md to any documentation page URL to get its markdown version.

# List Clients

This endpoint retrieves a detailed list of clients.

# OpenAPI definition

```json
{
  "openapi": "3.0.1",
  "info": {
    "title": "Core API",
    "version": "v1"
  },
  "servers": [
    {
      "url": "https://api.scalepad.com"
    }
  ],
  "paths": {
    "/v1/clients": {
      "get": {
        "summary": "List Clients",
        "parameters": [
          {
            "name": "page",
            "in": "query",
            "required": false
          },
          {
            "name": "filter",
            "in": "query",
            "required": false
          },
          {
            "name": "sort",
            "in": "query",
            "required": false
          }
        ],
        "responses": {
          "200": {
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
