---
updatedAt: 2026-04-23T21:49:21.000Z
---

Fetch the complete documentation index at: https://developer.scalepad.com/llms.txt. Use this file to discover all available pages before exploring further. Append .md to any documentation page URL to get its markdown version.

# Ingest Backup Results

Ingest backup results for a device.

# OpenAPI definition

```json
{
  "openapi": "3.0.1",
  "info": {
    "title": "Backup Radar API",
    "version": "v1"
  },
  "servers": [
    {
      "url": "https://api.scalepad.com"
    }
  ],
  "paths": {
    "/v1/backups/results": {
      "post": {
        "summary": "Ingest Backup Results",
        "parameters": [],
        "responses": {
          "202": {
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
          "deviceId": {
            "type": "string"
          },
          "status": {
            "type": "string"
          },
          "timestamp": {
            "type": "string"
          }
        }
      }
    }
  }
}
```
