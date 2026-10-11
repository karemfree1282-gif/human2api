# APIs: MCP and localhost REST

## MCP over stdio

```bash
h2a mcp --directory /absolute/path/to/workflows
```

The MCP server uses JSON-RPC 2.0 line-delimited messages over stdin/stdout with the 2025-11-25 protocol compatibility response. It supports `initialize`, `ping`, `tools/list`, `tools/call`, `resources/list`, and `prompts/list` (the last two return empty lists). Notifications have no response.

Each JSON workflow exposes exactly one MCP tool named `h2a_<name>`. Its argument schema follows the declared `inputs`. `h2a_list_workflows` reports installed workflows. No LLM service is called by the server.

MCP example initialization:

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"demo","version":"1.0"}}}
```

Read-only workflows can run without `H2A_ALLOW_WRITE`. Workflows marked `write` require that environment variable to be set to `1`. **Only enable it after reviewing the JSON workflows and your MCP client's permission prompts**. The server itself does not display a consent dialog for stdio tool calls.

## REST on localhost

```bash
h2a serve --port 8765
```

Open the dashboard in the browser. Its served HTML contains a fresh API token in the `h2a-token` meta tag; the dashboard automatically sends this token using the `X-H2A-Token` header. There is no persistent hard-coded credential. Do not expose the REST listener via a public proxy.

Available routes:

| Verb | Route | Description |
| --- | --- | --- |
| GET | `/health` | Readiness, no token needed |
| GET | `/api/workflows` | List installed workflows |
| GET | `/api/workflows/{name}` | Fetch one workflow JSON |
| POST | `/api/save/{name}` | Save validated JSON (`name` must match) |
| POST | `/api/run/{name}` | Launch run, returns `runId` |
| GET | `/api/runs/{runId}` | Poll until completed/failed |
| POST | `/api/record` | Start local visible Chromium recording |
| GET | `/api/recorder` | Query recording process status |
| GET | `/api/openapi.json` | Generated OpenAPI 3.1 contract |

POST example, substituting your dashboard's ephemeral token:

```bash
curl http://127.0.0.1:8765/api/run/create_invoice \
  -H "X-H2A-Token: YOUR_CURRENT_LOCAL_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"inputs":{"customer_name":"Alex","amount":49.99},"approve":true}'
```

Response: HTTP 202 with a runId. Poll `GET /api/runs/{runId}` with the same token for results. Error details exclude declared secret arguments on a best-effort basis; do not expose sensitive workflows publicly.

## Generate machine-readable OpenAPI

```bash
h2a openapi --directory workflows --port 8765 --output openapi.json
```

This generates a separate typed `POST /api/run/<name>` path for each valid workflow; input types and required fields come from the workflow.

## Troubleshooting

- `Chromium is not installed`: run `python -m playwright install chromium` or set `H2A_BROWSER_PATH`.
- `workflow has write permissions`: add `--approve` to a CLI call, check the dashboard approval checkbox, or set `H2A_ALLOW_WRITE=1` **only in a trusted MCP environment**.
- `navigation is outside allowedHosts`: review target domains and add specific hostnames, with no wildcards.
- `no matching element`: update the CSS selector or add alternatives in the workflow JSON.
- `invalid Host/Origin`: access `http://127.0.0.1:<port>` or `http://localhost:<port>` directly, not through a reverse proxy.
