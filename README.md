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

## Native Windows UI Automation and Android Companion — use real devices

### Windows end-to-end demo

1. Run `start-human2api.bat` once (requires Python 3.10+ and an internet connection). This installs `pywinauto` on Windows alongside the browser engine.
2. Double-click `start-windows-demo.bat` to open the **Human2API Windows Demo** application (Windows Forms).
3. In a second console inside the project directory, run:
   ```bat
   .venv\Scripts\h2a.exe run --workflow src\human2api\examples\windows_demo.json --allow-write
   ```
4. The demo must show **Saved: مرحبا Windows**. The automation uses native Windows UI Automation. It does not pretend to control Notepad or any unsupported desktop window.

Windows native automation requires a logged-in, interactive Windows desktop session; it cannot control Windows apps from Linux or run reliably in a headless Windows service session. Only applications matching `allowedApps` are eligible.

### Android USB companion end-to-end demo

1. Install **Android Studio**, Android SDK Platform **34** and Build Tools 34.0.0. On Windows, double-click `build-android.bat`, or run `python scripts/build_android.py`. It downloads checksum-verified Gradle 8.7 if Gradle is unavailable. The real debug APK appears at `android-companion/app/build/outputs/apk/debug/app-debug.apk` **only after a successful Android build**.
2. Enable Developer Options and USB Debugging on your Android device, connect via USB, and run `adb install -r android-companion/app/build/outputs/apk/debug/app-debug.apk`.
3. In the Companion app, grant Android Accessibility Service manually. For the built-in **self-test**, enter `dev.human2api.companion` as the allowed package, tap **Start 5-minute session**, and keep the demo controls visible. A private one-time pairing code is shown on the phone.
4. On the Windows PC, run:
   ```bat
   .venv\Scripts\h2a.exe android doctor
   .venv\Scripts\h2a.exe android run --workflow src\human2api\examples\android_companion_demo.json --allow-write
   ```
   When prompted, paste the one-time pairing code from the phone. The app should display **Saved: مرحبا Android**.

**Architecture:** The Windows host runs the Human2API Python server/runner; the Android phone runs the consent-scoped native companion app and receives commands via an ADB USB loopback tunnel. This is **not** a standalone Android Python server. All read/action commands require a time-limited pairing token and match the phone's explicit package allowlist. No root is required.

**Verification caveat:** This source release has unit-tested ADB/HTTP protocol and Windows UIA dispatch paths, but a real Android APK/device test and interactive Windows UIA test must be completed on the corresponding platforms. Missing SDK/ADB or unavailable desktop privileges are reported as blockers; fake successes and fake APKs are not generated.
