<div align="center">

# Human2API (v0.5.0)

**Teach a task once. Inspect its steps. Reuse it as a REST API, CLI command, scheduled job, or MCP tool.**

Browser (Playwright / Chromium) · Windows UIA · macOS AX · Linux AT-SPI / GTK · Android Companion

[![License](https://img.shields.io/badge/license-Apache%202.0-blue)](LICENSE)

[Quick Start](#quick-start) · [العربية (Arabic Documentation)](docs/README_AR.md) · [Security](SECURITY.md) · [Roadmap](docs/ROADMAP.md) · [Acceptance](docs/ACCEPTANCE.md)
</div>

Human2API turns an explicitly recorded, reviewed user workflow into reusable local automation across web browsers, desktop applications, and Android devices. The core engine runs locally without requiring any cloud account or paid API key.

## Key Capabilities in v0.5.0

- **Browser Engine (Playwright & Chromium WebDriver)**: Records and replays clicks, typing, selects, scrolling, multi-tabs (`open_tab`, `switch_tab`, `close_tab`), nested iframes (`framePath`), safe file uploads/downloads, and post-condition assertions (`assert_text`, `assert_visible`, `assert_url`, `assert_value`). Uses a real Selenium WebDriver or Playwright Chromium session. A loopback alias is selected only when the corresponding listener is reachable; restricted browser environments may still block navigation and must not be described as verified.
- **Desktop Accessibility Engine**: Accessibility-first automation for **Windows (`windows-uia`)**, **macOS (`macos-ax`)**, and **Linux (`linux-atspi` / GTK3+ATK & X11)** supporting Arabic and English Unicode text, multi-window focus, and dynamic window resize recalculation.
- **Android Companion (`android-companion`)**: Consent-scoped `AccessibilityService` with a 5-minute session TTL, package allowlist enforcement, password field exclusion, Arabic/Unicode input, ADB loopback bridge (`127.0.0.1:18765`), and one-tap immediate `STOP`.
- **4-Tier Self-Healing Engine**: Resolves UI changes across (1) primary selector, (2) recorded fallback selectors, (3) semantic accessibility role/name/context matching, and (4) optional consent-gated AI candidate selection—while strictly refusing ambiguous elements, privilege escalation, or duplicate execution of non-idempotent write actions.
- **Bilingual Visual Studio UI (Arabic RTL & English LTR)**: Full Dashboard, Visual Workflow Editor (add/delete/reorder steps & manage inputs without editing JSON), live run progress, immediate stop, scheduled tasks, privacy-redacted run history, Marketplace browser, and Dark/Light themes.
- **Signed Marketplace & Registry**: Publisher accounts, Ed25519 digital signatures (`manifest.json` + `workflow.json`), key pinning, version diffing, verified reviews, package yanking, abuse reporting, SQLite hot backup/restore, tamper-evident audit logs, and HTTPS/TLS verification.

## Quick Start — actually launch the app

**Windows (recommended):** Download or clone the repository, then double-click `start-human2api.bat`.
The launcher creates a private Python environment, installs the browser dependencies, and opens Studio in your default browser.
Python 3.10+ and an internet connection are required for the first installation.

**Linux / macOS:** From the checked-out source directory, run:

```bash
./start-human2api.sh
```

**Manual / advanced:**

```bash
python -m pip install -e ".[browser]"
python -m playwright install chromium  # only if no Chrome/Chromium is installed
h2a start
```

`h2a start` chooses a free loopback port, opens the local dashboard, and seeds a sample **Demo Invoice** workflow. To verify it really works, enable **Write Approval** in the dashboard and run **Demo Invoice**. It fills and submits a *local demonstration form* and checks the result (no real-world payment or invoice is created). To run headless: `h2a start --no-browser --port 8000`.

> You do **not** need Docker, GitHub Actions, an API key, or an Android device to use the local demo. Browser automation requires locally available Chromium plus Selenium or Playwright. The Studio itself works without either browser driver.

**Docker (Linux host network only):** For security the HTTP service binds to loopback, not to `0.0.0.0`; use `docker build -t human2api .` then `docker run --rm --network host -v "$HOME/Human2API-Workspace:/data" -w /data human2api` and open `http://127.0.0.1:8000/`. Ordinary `docker run -p 8000:8000` cannot expose a loopback-only listener from inside the container. Windows users should prefer the `.bat` launcher.

If automation fails, run `h2a doctor --json`; its diagnostics distinguish missing browser dependencies, OS device permissions, and unavailable native Android tooling.

## Example Workflow JSON

```json
{
  "schemaVersion": "0.5",
  "name": "Invoice Demo",
  "target": "browser",
  "mode": "write",
  "networkPolicy": "strict",
  "allowedHosts": ["127.0.0.1"],
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
      "url": "http://127.0.0.1:8000/demo"
    }
  ],
  "assertions": []
}
```

## Running the Engineering Verification Suite (`h2a complete`)

```bash
python3 scripts/complete.py --repair
```
