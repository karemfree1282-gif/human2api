# Changelog

## [0.1.0] - 2026-10-11

Initial alpha release candidate:

- Visible Chromium recorder with variable substitution rather than saved typed values.
- Versioned strict JSON workflow specification.
- Playwright replay, CSS selector fallbacks, validation, assertions and file downloads.
- Local dashboard and fake invoice demo.
- MCP stdio dynamic workflow tools and local token-authenticated REST API.
- Generated OpenAPI 3.1, security guide, contributor guide and browser tests.

**Not yet implemented:** desktop/Android recording, autonomous AI self-healing, cross-origin iframe capture or hosted accounts.

## 0.2.0 — multiplatform developer preview

- Added optional desktop runner and pointer-only desktop recorder for Windows/macOS/Linux.
- Added Android ADB runner, UIAutomator text selectors and interactive teaching CLI.
- Added opt-in semantic/AI browser selector recovery, never persisted automatically.
- Added local JSON workflow packaging, verification, manual installation and catalog.
- Added multi-tab/first-level named iframe capture; browser press/hover/drag/scroll support.
- Upgraded local dashboard with engine support/skill catalog panels and per-run healing permissions.
- Kept existing workflow schemaVersion 1 browser files compatible; extended target-specific schema.
- Added mocked cross-target security tests and documentation explaining hardware-validation gaps.

## 0.2.1 — public read-only community index

- Added HTTPS registry with package-index schema checks, download size bounds and disabled redirects.
- Added checksum-pinned opt-in installation (`h2a catalog --remote`, `h2a install-remote --approve`).
- Added public JSON index and an extensive mocked negative-case/integrity test suite.
- This does not supply signed publisher identity, vetted reviews, or a hosted execution service.

## 0.2.2 — persistent private history and public index UI

- Added local SQLite run journal with bounded retention and restart interruption recovery.
- Added token-authenticated metadata-only REST API for recent history.
- Added public read-only community index browser to the dashboard with no auto-installation.
- Improved unexpected runner-error sanitization, documentation and tests.
- No physical Android or native-desktop acceptance claims.
