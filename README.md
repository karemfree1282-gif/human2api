<div align="center">

# Human2API (v0.5.0)

**Teach a task once. Inspect its steps. Reuse it as a REST API, CLI command, scheduled job, or MCP tool.**

Browser (Playwright / Chromium) · Windows UIA · macOS AX · Linux AT-SPI / GTK · Android Companion

[![License](https://img.shields.io/badge/license-Apache%202.0-blue)](LICENSE)

[Quick Start](#quick-start) · [العربية (Arabic Documentation)](docs/README_AR.md) · [Security](SECURITY.md) · [Roadmap](docs/ROADMAP.md) · [Acceptance](docs/ACCEPTANCE.md)
</div>

Human2API turns an explicitly recorded, reviewed user workflow into reusable local automation across web browsers, desktop applications, and Android devices. The core engine runs locally without requiring any cloud account or paid API key.

## Key Capabilities in v0.5.0

- **Browser Engine (Playwright & Chromium WebDriver)**: Records and replays clicks, typing, selects, scrolling, multi-tabs (`open_tab`, `switch_tab`, `close_tab`), nested iframes (`framePath`), safe file uploads/downloads, and post-condition assertions (`assert_text`, `assert_visible`, `assert_url`, `assert_value`). Automatically resolves `127.0.0.1` managed browser blocks via `127.0.0.2` loopback binding so all 4 End-to-End URL tests execute and pass in real Chromium.
- **Desktop Accessibility Engine**: Accessibility-first automation for **Windows (`windows-uia`)**, **macOS (`macos-ax`)**, and **Linux (`linux-atspi` / GTK3+ATK & X11)** supporting Arabic and English Unicode text, multi-window focus, and dynamic window resize recalculation.
- **Android Companion (`android-companion`)**: Consent-scoped `AccessibilityService` with a 5-minute session TTL, package allowlist enforcement, password field exclusion, Arabic/Unicode input, ADB loopback bridge (`127.0.0.1:18765`), and one-tap immediate `STOP`.
- **4-Tier Self-Healing Engine**: Resolves UI changes across (1) primary selector, (2) recorded fallback selectors, (3) semantic accessibility role/name/context matching, and (4) optional consent-gated AI candidate selection—while strictly refusing ambiguous elements, privilege escalation, or duplicate execution of non-idempotent write actions.
- **Bilingual Visual Studio UI (Arabic RTL & English LTR)**: Full Dashboard, Visual Workflow Editor (add/delete/reorder steps & manage inputs without editing JSON), live run progress, immediate stop, scheduled tasks, privacy-redacted run history, Marketplace browser, and Dark/Light themes.
- **Signed Marketplace & Registry**: Publisher accounts, Ed25519 digital signatures (`manifest.json` + `workflow.json`), key pinning, version diffing, verified reviews, package yanking, abuse reporting, SQLite hot backup/restore, tamper-evident audit logs, and HTTPS/TLS verification.

## Quick Start

```bash
git clone https://github.com/karemfree1282-gif/human2api.git
cd human2api
python3 -m pip install -e ".[browser,vault,signing]"
h2a init
h2a serve --host 127.0.0.1 --port 8000
```

## Example Workflow JSON

```json
{
  "schemaVersion": "0.5",
  "name": "Invoice Demo",
  "target": "browser",
  "mode": "write",
  "networkPolicy": "strict",
  "allowedHosts": ["127.0.0.1", "127.0.0.2"],
  "inputs": {
    "customer": {
      "type": "string",
      "required": true,
      "sensitive": false,
      "default": "شركة الأمل"
    }
  },
  "steps": [
    {
      "id": "step_1",
      "action": "goto",
      "url": "http://127.0.0.2:8000/demo"
    }
  ],
  "assertions": []
}
```

## Running the Engineering Verification Suite (`h2a complete`)

```bash
python3 scripts/complete.py --repair
```
