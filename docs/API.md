# Interfaces - v0.4.0

## Local REST

`h2a serve` opens `http://127.0.0.1:8765`. The page receives a per-server token; all `/api/` calls require `X-H2A-Token`. Host/Origin must match. Do not expose this service publicly. The independent registry is documented in [REGISTRY.md](REGISTRY.md).

`GET /api/openapi.json` returns OpenAPI 3.1 with typed workflow input schemas. `h2a complete --repair` regenerates the checked-in example; live installed workflows can differ.

| Route | Purpose |
| --- | --- |
| `GET /api/workflows`, `/api/workflows/{name}` | List/inspect definitions |
| `POST /api/run/{name}` | `{inputs, approve, healSelectors, aiHeal}`; returns 202 and runId |
| `GET /api/runs/{runId}` | Progress/result with bounded retention |
| `POST /api/runs/{runId}/cancel` | Cooperative cancellation, not OS rollback |
| `GET /api/history` | Persistent metadata only |
| `GET /api/editor/workflows/{name}` | Definition and revision |
| `POST /api/editor/validate` | Validate without executing |
| `POST /api/editor/save/{name}` | Required `If-Match` revision (`new` to create); conflict 409 |
| `GET /api/platforms` | Dependency probes, not hardware certification |
| `GET /api/catalog`, `/api/catalog/remote` | Package listings, not trusted auto-installation |
| `GET /api/schedules`, `/api/recorder` | Schedule/recording status |

A token does not replace write consent. `aiHeal:true` separately permits configured-provider metadata transfer. There is no public registry execution endpoint.

## MCP stdio

Run `h2a mcp --directory /absolute/path/to/workflows`. UTF-8 JSON-RPC messages are newline-delimited; stdout is protocol-only. Every valid workflow exposes a typed `h2a_<name>` tool. Clients must present human approval; writes also require `H2A_ALLOW_WRITE=1`.

Modern clients use 2026-07-28 metadata and `server/discover`. Legacy 2024-11-05, 2025-03-26, 2025-06-18 and 2025-11-25 initialized sessions are handled separately. Unsupported versions produce a structured error. Bounded tool calls do not block the input loop; cancellation/progress work during cooperative waits. Native OS calls may finish before observing cancellation. EOF cancels active work. Pagination binds cursors to a workflow-directory snapshot.

```json
{"mcpServers":{"human2api":{"command":"h2a","args":["mcp","--directory","/absolute/path/to/workflows"],"env":{"H2A_ALLOW_WRITE":"0"}}}}
```

## CLI

New commands: `init`, `studio`, `batch`, `vault`, `registry`, `registry-install`, `complete`. Each exposes `--help`. `pack --sign-key publisher.pem --release-version 1.0.0` binds a registry release to its signature. Legacy local packages remain inspectable but unsigned packages cannot become trusted registry releases.

References: https://modelcontextprotocol.io/specification ; https://developer.android.com/reference/android/accessibilityservice/AccessibilityService ; https://playwright.dev/python/docs/intro
