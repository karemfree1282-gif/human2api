# Architecture

Browser DOM / smart desktop pointer / Android companion capture -> strict inspectable workflow JSON -> visual editor and CAS revision storage -> CLI / loopback REST / MCP -> typed inputs, explicit write approval and device lease -> Playwright / UIA / AX / AT-SPI / scoped Android -> assertions, cancellation and private results.

`contracts.py` defines allowed actions, required fields and generated schema. `models.py` adds semantic validation of templates, values, paths, hosts and target-specific permissions. Unknown actions never become executable code. Legacy v1 browser workflows remain supported.

`runner.py` enforces permission and artifact policies. `execution.py` and `leases.py` serialize native devices across cooperating processes and cancel cooperatively. Only safe reads retry. `healing.py` recommends a supplied candidate, not new code; adapters re-resolve it uniquely within the original scope.

`vault.py` encrypts secrets and rejects stale writes. `history.py` stores status metadata only. `editor.py` implements revision-aware saves and private backups. `batch.py` validates all rows before side effects. `workspace.py` copies packaged examples without overwriting user files.

`http_server.py` exposes a bounded loopback-only API. `studio.py` optionally presents the same app through pywebview with no privileged JavaScript bridge. `mcp_server.py` supports modern 2026-07-28 metadata and legacy initialized sessions, asynchronous bounded calls, progress and cancellation.

The registry is a separate process/trust boundary and never executes tools. It stores operator-enrolled keys, hashed tokens, immutable signed versions, revocation/reviews/audit events in SQLite. Clients pin the key and signed version before installation. Backup/restore is explicit. Caddy terminates HTTPS for this independent service, never for the runner or Android bridge.

`completion.py` binds operator evidence to an implementation digest and checks real command/JUnit results. Native and Android builders require actual successful output artifacts. Mocked bindings, generated JSON and source listings are never treated as hardware or compilation evidence.
