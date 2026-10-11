# Architecture: small, inspectable, offline-first

```text
+------------------------+              +-----------------------+
| Human (Chromium)       |              | Agent (MCP client)    |
| clicks and form edits  |              | h2a_create_invoice()  |
+-----------+------------+              +-----------+-----------+
            | DOM events                              | JSON-RPC stdio
            v                                         v
+------------------------+              +-----------------------+
| Recorder (recorder.py) |              | MCP adapter           |
| CSS selectors / fields |              | typed input schemas   |
| values never captured  |              +-----------+-----------+
+-----------+------------+                          |
            |                                       |
            v                                       v
+------------------------------------------------------------+
| WORKFLOW JSON: source of truth, visible in dashboard       |
| schemaVersion / allowedHosts / inputs / actions / outputs  |
+----------------------------+-------------------------------+
                             |
             +---------------+----------------+
             |                                |
             v                                v
+--------------------------+     +---------------------------+
| Playwright replay runner |     | Local-only REST/dashboard |
| fresh browser context    |     | 127.0.0.1 + token         |
| verify / extract / files |     | OpenAPI / editor / demo   |
+--------------------------+     +---------------------------+
```

## Trust boundaries

- Recording runs on the user's machine. Javascript captures action selectors and input field identities. **It does not send or persist typed input values.** Password input names and CSS selectors may still reveal sensitive metadata and should be inspected.
- Replaying runs in a fresh Chromium context. It does not inherit the user's actual Chrome sessions/cookies. Authentication-dependent flows require a future explicit, secured session-management feature.
- A workflow is constrained to enumerated operations. It cannot contain Python or Javascript to evaluate, but **clicks and navigation can trigger powerful actions on the target site**.
- Only main document navigations are checked against `allowedHosts`. This is not a network sandbox for subresources, JS fetches or other browser internals.
- Dashboard REST binds to loopback only, rejects unexpected Host/Origin, requires an ephemeral `X-H2A-Token` for `/api/*`, and stores execution artifacts under `runs/` (ignored by Git). If your machine is compromised, local server controls do not create a security boundary.
- MCP has no UI consent mechanism by itself. It refuses write flows unless `H2A_ALLOW_WRITE=1`; downstream MCP clients are expected to request user approval.

## Workflow format

A versioned JSON object with `name`, `startUrl`, `description`, `permissions`, `allowedHosts`, `inputs`, and `steps`. Supported actions:

| Action | Fields | Behavior |
| --- | --- | --- |
| `navigate` | `url` | Navigate (allowed host only) |
| `click` | `selector` | Click target |
| `fill` | `selector`, `value` | Fill text input |
| `select` | `selector`, `value` | Choose an HTML select option |
| `check` | `selector`, `checked` | Set checkbox/radio state |
| `wait` | `selector` | Wait for visible element |
| `assert_text` | `selector`, `text` | Verify substring in element |
| `extract_text` | `selector`, `as` | Return text in an output field |
| `download` | `selector`, optional `filename` | Click, await download, save locally |
| `screenshot` | optional `filename` | Capture viewport to local file |

Actions support `timeoutMs` (100-120000) and `alternatives` (up to eight CSS fallbacks). All URL/template strings use `{{field_name}}`, no eval.

## Near-term design improvements

- Prefer stable accessibility selectors and user-guided fallbacks.
- Add recorder pause/resume, tab synchronization, navigation snapshots and screenshot redaction.
- Add explicit approved browser session stores (encrypted locally) and step-by-step diff reviews.
- Add per-operation allowlisting and auditable permissions rather than broad workflow approval.
- Run the browser in a stronger restricted sandbox for untrusted sites.

See [ROADMAP.md](ROADMAP.md).
