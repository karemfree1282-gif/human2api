## v0.3.0 — Safer execution and publisher trust

- Cooperative cancellation and step progress for localhost REST/dashboard; bounded parallel executions.
- Windows UIA selectors, text extraction/assertions and Unicode ValuePattern entry, with optional dependencies.
- Opt-in local interval scheduler with locked-down input JSON files and explicit write authorization.
- Signed Ed25519 workflow packages (manifest v2), key generation and pinned publisher verification.
- Read-only retries only; mutating actions cannot be automatically repeated.
- Plan/history/keygen/inspect-desktop/scheduler CLI commands; JSON Schema and documentation updates.
- Hardware acceptance across Windows/macOS/Linux/Android and complete GitHub Actions runner validation still outstanding.

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
