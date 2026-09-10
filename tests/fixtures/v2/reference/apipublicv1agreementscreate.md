---
updatedAt: 2026-04-23T21:49:21.000Z
---

Fetch the complete documentation index at: https://developer.scalepad.com/llms.txt. Use this file to discover all available pages before exploring further. Append .md to any documentation page URL to get its markdown version.

# Create Agreement

Create an agreement with full details.

# OpenAPI definition

```json
{
  "openapi": "3.0.1",
  "info": {
    "title": "Lifecycle Manager API",
    "version": "v1"
  },
  "servers": [
    {
      "url": "https://api.scalepad.com"
    }
  ],
  "paths": {
    "/api/public/v1/agreements": {
      "post": {
        "summary": "Create Agreement",
        "parameters": [],
        "responses": {
          "201": {
            "description": "x"
          },
          "400": {
            "description": "x"
          }
        },
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/Body"
              }
            }
          }
        }
      }
    }
  },
  "components": {
    "schemas": {
      "Body": {
        "type": "object",
        "properties": {
          "name": {
            "type": "string"
          },
          "clientId": {
            "type": "string"
          },
          "startDate": {
            "type": "string"
          }
        }
      }
    }
  }
}
```
