---
updatedAt: 2026-09-09T00:00:00.000Z
---

Fetch the complete documentation index at: https://developer.scalepad.com/llms.txt. Use this file to discover all available pages before exploring further. Append .md to any documentation page URL to get its markdown version.

# List Assessments

Retrieve a comprehensive list of all assessments.

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
    "/api/public/v1/assessments": {
      "get": {
        "summary": "List Assessments",
        "parameters": [],
        "responses": {
          "200": {
            "description": "x"
          },
          "401": {
            "description": "x"
          },
          "429": {
            "description": "x"
          }
        },
        "deprecated": true
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
