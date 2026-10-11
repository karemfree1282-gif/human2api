# FAQ

**Is Human2API an autonomous AI agent?** No. v0.1 is a deterministic browser task recorder and runner. It exposes tools over the MCP protocol for agent clients; it does not contain its own AI model.

**Can it use desktop applications or Android?** Not in v0.1. Only the top-level Chromium tab is supported for recording.

**Does it store what I type during recording?** The recorder discards typed form values and replaces them with named inputs. URLs, selectors and attribute names can still contain personal data; review the generated JSON before sharing.

**Does it send anything to a cloud backend?** The app has no built-in telemetry or cloud sync. Browser navigation naturally sends requests to websites you visit, and external assets on those pages can make third-party requests.

**Can I run this on a production bank or payment site?** We do not recommend doing that with this alpha. Test on an isolated account first, inspect every step, and understand the browser and network permissions.

**Is the local REST API safe to expose on the internet?** No. The HTTP server binds to 127.0.0.1 and assumes a trusted local machine. Never reverse-proxy it publicly as-is.

**How do I contribute?** Start with a reproducible issue or an improvement to selectors/tests, read [CONTRIBUTING.md](../CONTRIBUTING.md), and submit a focused pull request.

**Why is this alpha?** Many edge cases remain: multiple tabs, cross-origin iframes, desktop apps, resilient DOM recordings across web app upgrades, and human-in-the-loop approvals from arbitrary MCP clients.
