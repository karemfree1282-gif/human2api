# Architecture: portable workflows, constrained executors

```text
[Human browser recorder]         [Human pointer recorder]       [Human guided ADB recorder]
             \                            |                           /
              +---------------------------+--------------------------+
                                          |
                         [Validated workflow JSON, schemaVersion 1]
                               |                    |
                     [MCP JSON-RPC stdio]      [REST / dashboard]
                               |                    |
                               +----------+---------+
                                          |
                                [Policy + input validation]
                                    write approval
                                          |
                    +---------------------+--------------------------+
                    |                     |                          |
                [Playwright]          [PyAutoGUI]               [ADB CLI]
              isolated browser      active OS session        selected device
                    |                     |                          |
                DOM assertions       image assertion           UIAutomator
                screenshots          screenshot                screenshot
                    +---------------------+--------------------------+
                                          |
                                [Local run artifacts]
```

## Backward compatibility and target model

A `schemaVersion: 1` workflow without `target` is a **browser** workflow. A new explicit `"target":"desktop"` or `"target":"android"` uses its own strictly allowed action set, with no `startUrl`. Workflows remain plain inspectable JSON. The file's `inputs` define typed required values, with no persisted defaults for secrets.

`models.py` is the single source of truth for allowed actions and type validation. `runner.py` routes to browser/desktop/Android executors and enforces write approval before touching the target. It does not invoke user-provided shell commands, Python snippets, or JS actions from workflow files.

## Recording

- **Browser**: an injected event listener captures element selectors and input field identities, *not* input values. First-level iframes must have stable ID or name. Tab changes become `switch_tab` steps. Cross-domain navigation is constrained by explicit host list, but remote JS and subresources remain out of network-sandbox scope.
- **Desktop**: `pynput` monitors pointer clicks and scroll events during an explicit session that stops on F12. No typed keys or clipboard contents are intercepted. Desktop text steps must be authored using placeholders.
- **Android**: interactive CLI translates user-entered commands into actions and executes selected actions on the authorized device via ADB; text input placeholders never store entered credentials.

## Executor trust boundaries

- **Browser**: starts a fresh Playwright context with service workers blocked; navigation to unlisted hosts is aborted. Semantic healing checks unique visible ARIA/label targets. With explicit per-run consent only, an OpenAI-compatible endpoint can recommend CSS selectors from sanitized interactive element metadata, not full HTML. Suggestions are not applied permanently.
- **Desktop**: GUI is controlled through optional PyAutoGUI in the user's current desktop login. It has no OS sandbox. Upper-left-corner failsafe applies; keyboard shortcuts are allowlisted.
- **Android**: ADB CLI commands are invoked using argument lists. Device selection must be unambiguous/authorized. XML UI lookup requires exactly one matching element. ADB text support is limited to a safe ASCII subset.
- **MCP**: runs over stdio, not a network socket, and requires `H2A_ALLOW_WRITE=1` for write workflows; the connected MCP client must provide actual human approval.
- **REST**: local loopback binding, strict Host/Origin and unpredictable per-server API token. Does not support public ingress or independent user authentication.
- **Portable packages**: two JSON files plus a verified checksum; no executable content, no overwrite on install. Sha256 is not a publisher trust signature.

## Main modules

- `models.py`: data and action policy
- `recorder.py`: browser capture
- `desktop.py`: optional GUI executor and pointer recorder
- `android.py`: authorized device driver + guided recorder
- `healing.py`: opt-in browser selector suggestions
- `marketplace.py`: verified local-only workflow packages
- `runner.py`: orchestration + Chromium target
- `mcp_server.py`, `http_server.py`, `cli.py`: caller-facing APIs

## Risks and future work

Native cross-platform accessibility selectors, Unicode text handling, genuine device tests, secure credential vault, team RBAC, online signed marketplace, and network isolation are future work. See [Security](../SECURITY.md) and [Roadmap](ROADMAP.md).
