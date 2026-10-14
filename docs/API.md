# Human2API Local REST & MCP API Reference (v0.5.0)

All local REST endpoints bind to `127.0.0.1` (or `127.0.0.2`), require `X-H2A-Token` or `Authorization: Bearer <token>`, reject duplicate identity headers, and enforce `Host`/`Origin` loopback validation.

## Endpoints

- `GET /api/v1/health` — Health & vault lock status.
- `GET /api/v1/status` — Workspace counts and active settings.
- `GET /api/v1/workflows` & `POST /api/v1/workflows` — List and save workflows.
- `PUT /api/v1/workflows/<name>` & `DELETE /api/v1/workflows/<name>` — Visual editor CAS mutations (`add_step`, `delete_step`, `reorder_steps`, `set_input`).
- `POST /api/v1/record/compile` — Compile recorded UI events into a parameterized `Workflow`.
- `POST /api/v1/run` — Execute a workflow synchronously or asynchronously (`allowWrite` required for write workflows).
- `POST /api/v1/runs/<run_id>/cancel` — Immediately cancel an active run.
- `GET /api/v1/history` — Privacy-redacted run history journal.
- `GET /api/v1/schedules`, `POST /api/v1/schedules`, `PATCH /api/v1/schedules/<id>`, `DELETE /api/v1/schedules/<id>` — Manage recurring scheduled tasks.
- `GET /api/v1/marketplace/packages`, `POST /api/v1/marketplace/publishers`, `POST /api/v1/marketplace/publish`, `POST /api/v1/marketplace/install`, `POST /api/v1/marketplace/yank`, `POST /api/v1/marketplace/reviews`, `POST /api/v1/marketplace/report`, `GET /api/v1/marketplace/diff` — Ed25519 Signed Marketplace operations.
- `POST /mcp` — JSON-RPC 2.0 Model Context Protocol endpoint (`initialize`, `tools/list`, `tools/call`, `ping`).

## Example Run Request

```json
{
  "workflowName": "synthetic_login.json",
  "allowWrite": true,
  "inputs": {
    "customer_name": "شركة النور",
    "invoice_amount": "500.00"
  }
}
```
