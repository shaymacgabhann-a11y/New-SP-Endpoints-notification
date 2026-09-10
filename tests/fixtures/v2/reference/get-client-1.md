---
updatedAt: 2026-04-23T21:49:21.000Z
---

Fetch the complete documentation index at: https://developer.scalepad.com/llms.txt. Use this file to discover all available pages before exploring further. Append .md to any documentation page URL to get its markdown version.

# Get Client

This endpoint retrieves a single client, identified by its unique ID.

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
    "/v1/clients/{id}": {
      "get": {
        "summary": "Get Client",
        "parameters": [],
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
