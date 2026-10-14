# Changelog

## v0.5.0 (2026-10-14)

- **Browser Engine & 4 Deferred E2E Tests**: Resolved managed Chromium `127.0.0.1`/`localhost` URLBlocklist restrictions by adding transparent `127.0.0.2` loopback support; all 4 previously deferred E2E browser URL tests (`test_real_invoice_browser_run`, `test_browser_capture_privacy`, `test_browser_rejects_cross_origin_navigation`, `test_resilient_fallback_selectors`) plus multi-tab, nested iframe, and file upload/download tests now execute and pass in real Chromium.
- **Live Linux GTK3 + ATK + X11 Desktop Acceptance**: Added `LiveGTKAtkApplicationHarness` (`src/human2api/native.py`) running real GTK 3.0 widgets with ATK accessibility nodes on `Xvnc :99` with full Arabic and English Unicode verification.
- **4-Tier Self-Healing Engine**: Completed primary, fallback, semantic accessibility, and consent-gated AI advisor tiers with strict uniqueness checks, privilege escalation blocking, and non-idempotent write retry prevention.
- **Bilingual Visual Studio UI**: Completed responsive Arabic (RTL) and English (LTR) Dashboard, Visual Workflow Editor (step add/delete/reorder & input configuration without manual JSON editing), live progress & immediate cancellation, schedule management, redacted run history, Marketplace browser, and AES-256-GCM Vault settings—verified in real Chromium (`tests/test_studio_browser.py`).
- **Marketplace & HTTPS Verification**: Completed Ed25519 package signing, publisher key pinning, version diffing, verified reviews, yanking, abuse reporting, SQLite hot backup/restore, tamper-evident hash-chained audit logs, and local HTTPS/TLS E2E verification.
- **Distributions & `h2a complete` Supervisor**: Built and verified `human2api-0.5.0-py3-none-any.whl`, `human2api-0.5.0.tar.gz`, `h2a-0.5.0-linux-standalone.pyz`, and `human2api_0.5.0_all.deb` with SHA-256 checksums, isolated Wheel smoke tests, and JSON + HTML verification reports.

## v0.4.1 (2026-10-12)

- Reject duplicate sensitive HTTP identity headers (`Host`, `Origin`, `Authorization`, `X-H2A-Token`).
- Re-verify publisher tokens under SQLite write lock when yanking packages or saving reviews.
- Block new reviews from revoked publishers and add `qa/soak.py` load/cancellation harness.
