# Changelog

## 0.4.1 - 2026-10-12

- Reject duplicate Host, Origin, Authorization and local-token headers before processing requests.
- Revalidate publisher tokens under the SQLite write lock when yanking packages or saving reviews; revocation and rotation cannot race these writes.
- Reject new ratings on revoked publishers.
- Add 15 live HTTP/TLS, concurrent publication and authorization regression tests.
- Add a reproducible local load/cancellation probe in `qa/soak.py`.
- Native installers, physical-device acceptance and public hosting remain separate, unverified release gates.

## 0.4.0 - 2026-10-12

### Added
- Native macOS AX and Linux AT-SPI alongside Windows UIA; scoped recovery and Unicode input.
- Consent-first Android companion source, bounded loopback bridge and native selectors.
- Visual editor, optional desktop Studio, revision conflict protection, examples and typed batches.
- Encrypted vault, cross-process device leases, sensitive artifact opt-in and result limits.
- Signed/version-bound registry packages, enrolled accounts, pinned-key upgrades, reviews, revocation, token rotation and backup/restore.
- Modern/legacy MCP with asynchronous cancellation/progress and snapshot-safe pagination.
- One-command release checks, native/Android builders and draft-release assembly.

### Fixed
- Python 3.10 metadata-test compatibility and unsafe ambiguous selector handling.
- Input-variable collisions across tabs/frames/controls; nested stable iframe capture/replay.
- Retry safety, request framing/connection bounds, stale vault/editor writes and secret-result truncation.

### Evidence boundaries
- Local unit, HTTP and Chromium DOM tests are separate from blocked URL E2E tests and physical acceptance.
- GitHub runner failure is an account billing lock, not removable by a source patch.
- Build scripts/source are not claims of compiled APKs, OS-signed installers or deployed hosting.

## v0.3.0 — Safer execution and publisher trust

- Cooperative cancellation and step progress for localhost REST/dashboard; bounded parallel executions.
- Windows UIA selectors, text extraction/assertions and Unicode ValuePattern entry, with optional dependencies.
- Opt-in local interval scheduler with locked-down input JSON files and explicit write authorization.
- Signed Ed25519 workflow packages (manifest v2), key generation and pinned publisher verification.
- Read-only retries only; mutating actions cannot be automatically repeated.
- Plan/history/keygen/inspect-desktop/scheduler CLI commands; JSON Schema and documentation updates.
- Hardware acceptance across Windows/macOS/Linux/Android and complete GitHub Actions runner validation still outstanding.

## 0.2.0— multiplatform developer preview

- Added optional desktop runner and pointer-only desktop recorder for Windows/macOS/Linux.
- Added Android ADB runner, UIAutomator text selectors and interactive teaching CLI.
- Added opt-in semantic/AI browser selector recovery, never persisted automatically.
- Added local JSON workflow packaging, verification, manual installation and catalog.
- Added multi-tab/first-level named iframe capture; browser press/hover/drag/scroll support.
- Upgraded local dashboard with engine support/skill catalog panels and per-run healing permissions.
- Kept existing workflow schemaVersion 1 browser files compatible; extended target-specific schema.
- Added mocked cross-target security tests and documentation explaining hardware-validation gaps.

## [0.1.0] - 2026-10-11

Initial alpha release candidate:

- Visible Chromium recorder with variable substitution rather than saved typed values.
- Versioned strict JSON workflow specification.
- Playwright replay, CSS selector fallbacks, validation, assertions and file downloads.
- Local dashboard and fake invoice demo.
- MCP stdio dynamic workflow tools and local token-authenticated REST API.
- Generated OpenAPI 3.1, security guide, contributor guide and browser tests.

**Not yet implemented:** desktop/Android recording, autonomous AI self-healing, cross-origin iframe capture or hosted accounts.
