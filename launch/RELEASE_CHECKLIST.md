# Human2API v0.5.0 Release & Launch Checklist

- [x] Browser Engine: Multi-tabs, nested iframes, safe file upload/download, secret redaction, assertions, and 4/4 E2E URL tests passing in real Chromium via `127.0.0.2` loopback.
- [x] Desktop Engine: Windows UIA (`windows-uia`), macOS AX (`macos-ax`), and live Linux GTK3+ATK+Xvnc (`linux-atspi`) verified with Arabic & English Unicode input.
- [x] Android Companion: Consent-scoped `AccessibilityService` (5-min TTL), package allowlist, password exclusion, and immediate `STOP` receiver.
- [x] 4-Tier Self-Healing: Primary, fallback, semantic accessibility, and consent-gated AI advisor with non-idempotent write retry protection.
- [x] Bilingual Visual Studio UI: Arabic RTL & English LTR, Dark/Light themes, visual step editor, live progress, scheduler, redacted history, and AES-256-GCM Vault settings.
- [x] Ed25519 Signed Marketplace: Publisher accounts, key pinning, version diffing, verified reviews, yanking, abuse reporting, SQLite hot backup/restore, audit chain, and HTTPS/TLS verification.
- [x] Distributions Built: Wheel (`.whl`), Source (`.tar.gz`), Linux ELF (`h2a-0.5.0-linux-x86_64`), Linux DEB (`.deb`), Linux PYZ (`.pyz`), Windows PE64 CLI/GUI (`.exe`), and macOS Bundle (`.app.tar.gz`).
