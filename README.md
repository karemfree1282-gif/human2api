<div align="center">
  <img src="docs/assets/logo.svg" alt="Human2API logo" width="84" />

  # Human2API

  **Teach a task once. Run it from your terminal, REST API, or any MCP-compatible AI agent.**

  <p>Browser · Windows / macOS / Linux desktop · Android (ADB) · Local-first · Open source</p>

  [![CI](https://github.com/karemfree1282-gif/human2api/actions/workflows/ci.yml/badge.svg)](https://github.com/karemfree1282-gif/human2api/actions/workflows/ci.yml)
  [![Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-70ecc3)](LICENSE)
  [![Python](https://img.shields.io/badge/python-3.10%2B-85b9ff)](pyproject.toml)
  [![MCP](https://img.shields.io/badge/MCP-stdio-70ecc3)](docs/API.md)
  [![Local-first](https://img.shields.io/badge/privacy-local--first-98d2ff)](SECURITY.md)

  **[Arabic guide](docs/README_AR.md)** · **[Quick start](#quick-start)** · **[Platforms](#platform-support)** · **[MCP](#connect-your-ai-agent)** · **[API](docs/API.md)** · **[Security](SECURITY.md)** · **[Contribution](CONTRIBUTING.md)**

  <img src="docs/assets/dashboard-preview.webp" alt="Human2API local workflow dashboard" width="850" />
</div>

---

> **v0.3 development release.** The browser engine has automated local tests and the other platform engines have mocked unit tests, but physical Windows/macOS/Linux app and Android device acceptance tests are not yet complete. This project is **not** advertised as production-ready, a hosted cloud service, or a universal API for every app.

## The problem

Plenty of software has no public API. Human2API turns an *explicit, inspected workflow* into a reusable local tool. No generated code executes inside workflow definitions. Workflows are human-readable JSON, and write actions require explicit approval (either per-run, or once when the user deliberately creates a recurring local schedule).

```
Teach a browser / desktop / Android task
          ↓
Review & parameterize its JSON actions
          ↓
Run with verification and explicit permissions
          ↓
CLI  ·  MCP tool  ·  Local REST API
          ↓
Share a checksummed .h2a.zip workflow with others
```

## Quick start

**Browser (Python 3.10+)**

```bash
git clone https://github.com/karemfree1282-gif/human2api.git
cd human2api
python -m pip install -e .
python -m playwright install chromium
h2a serve
```

Open **http://127.0.0.1:8765**. A local fake-invoice sandbox is served at `/demo`; it never processes payments.

```bash
h2a check create_invoice
h2a run create_invoice --data '{"customer_name":"Alex","amount":49.99}' --approve
```

**Desktop (Windows, macOS, Linux)**

```bash
python -m pip install -e '.[desktop]'
h2a record-desktop --name mouse_demo
# Windows with stable UI Automation selectors (optional):
# h2a record-desktop --name smart_demo --smart
# Perform only the mouse clicks / scrolls you want recorded, then press F12.
# No keyboard content, passwords or clipboard text is captured.
h2a check mouse_demo
h2a run mouse_demo --approve
```

The desktop recorder captures **pointer actions only**. On Windows, `--smart` attempts to record non-password UIA automation IDs for clicks and falls back to coordinates when IDs are unavailable. It never records typed text. To enter values, edit the generated JSON and add `type_text` with a `{{variable}}` declaration under `inputs`. The current desktop text backend supports **ASCII**, and visible UI coordinates are resolution-dependent. Set mouse to the upper-left corner to activate PyAutoGUI's failsafe. `--show-browser` only applies to the browser target.

**Android (USB or emulator + Android platform-tools)**

1. Enable **USB debugging** on your own/test Android device and authorize the connected computer.
2. Install Android platform-tools so the `adb` executable is on PATH.
3. Record guided commands and run a workflow:

```bash
h2a devices
h2a record-android --name android_demo
# Commands: tap X Y, tap-text TEXT, input NAME, back, wait MS, assert TEXT, screenshot, done
h2a check android_demo
h2a run android_demo --approve
```

The Android recorder uses a **guided CLI** rather than passive touch capture. `input NAME` saves a placeholder, not the input value. UI text selectors are built from UIAutomator XML; Android text injection supports only a conservative ASCII subset. Device UI permissions and third-party app restrictions still apply; root is not required.

## Platform support

| Capability | Browser | Desktop | Android |
| --- | --- | --- | --- |
| Record actions | DOM events, tabs, named iframes | Pointer clicks & scroll; Windows UIA inspect | Guided ADB commands |
| Replay | Playwright | PyAutoGUI (optional) | Android platform-tools |
| Parameterized text input | Yes | ASCII mouse backend; Unicode through Windows UIA | Restricted ASCII |
| Visual/UI assertions | DOM text | Reference image (optional OpenCV) | UIAutomator text |
| Screenshots | Yes | Yes | Yes |
| MCP / REST / CLI | Yes | Yes | Yes |
| Automatic failure recovery | Optional semantic + opt-in AI selector suggestions; read-only retries | Read-only UIA verification retries | Android assertion retries |
| Verified on actual target devices | Chromium DOM tests; network E2E deferred in managed environment | Simulated UIA and mocked GUI tests only | Mocked ADB tests only |

Browser workflows are self-contained JSON. Captured form **values are discarded immediately** and replaced by input variables; URLs with query parameters are scrubbed at capture time. New-tab switching and named/ID-based first-level iframe selectors are supported. Not all browsers, operating system dialogs, canvas apps, or inaccessible desktop UIs work.

## Browser workflow recording

```bash
h2a record https://example.org --name my_browser_task
```

Interact in the new Chromium window and select **Stop & save**. The saved workflow contains CSS selectors, fallback selectors, and optional aria-label/role hints. It never stores typed values. Inspect it before running it on anything sensitive.

```json
{
  "action": "fill",
  "selector": "#customer-name",
  "alternatives": ["input[name=\"customer_name\"]"],
  "label": "Customer name",
  "value": "{{customer_name}}"
}
```

To make a write run, use `--approve`. A read-only workflow must contain only non-mutating steps. The browser engine blocks top-level/iframe navigation to unapproved hosts but is **not** a complete network sandbox: remote pages can make requests; use separate test profiles and accounts.

## Opt-in selector healing

When a browser selector no longer resolves, the runner can try **semantic aria labels/roles**. This never persists a change automatically:

```bash
h2a run create_invoice --data '{"customer_name":"Alex","amount":49.99}' --approve --heal-selectors
```

Optional AI suggestions work through **your explicitly configured OpenAI-compatible endpoint**. They are OFF by default. Enabling them transmits up to 70 **sanitized element metadata records** (IDs, names, roles, aria labels, test IDs) to the endpoint; these may still include identifying data. Form values, cookies and full HTML are not included. Always review suggestions.

```bash
export H2A_AI_ENDPOINT="https://api.openai.com/v1/chat/completions"
export H2A_AI_MODEL="gpt-4.1-mini"
export H2A_AI_API_KEY="<set-in-your-shell-not-in-source>"
h2a run create_invoice --data-file inputs.json --approve --heal-selectors --ai-heal
```

Only a unique visible element can be used as a recovered selector. AI does not execute scripts and cannot silently modify workflow files. The local dashboard also requires per-run AI-healing consent.

## Connect your AI agent

Use the MCP stdio adapter with any client supporting the MCP tools protocol:

```json
{
  "mcpServers": {
    "human2api": {
      "command": "h2a",
      "args": ["mcp", "--directory", "/absolute/path/to/workflows"],
      "env": {"H2A_ALLOW_WRITE": "0"}
    }
  }
}
```

One typed `h2a_<workflow>` tool is registered for every local valid workflow. Read-only actions work by default. Write workflows require `H2A_ALLOW_WRITE=1` and consent enforced by **your MCP client**; Human2API does not have an interactive approval dialog inside MCP.

## Share workflows: local catalog and packages

```
h2a pack create_invoice --output catalog/create_invoice.h2a.zip --publisher community
h2a catalog --catalog-dir catalog
h2a verify catalog/create_invoice.h2a.zip
h2a install catalog/create_invoice.h2a.zip --approve --directory other_workflows
```

`.h2a.zip` contains exactly a manifest and workflow JSON. Unsigned v1 checksums detect corruption; optional **Ed25519-signed v2 packages** support a pinned publisher public key. A valid signature alone does not establish a trustworthy publisher. Nothing executable gets extracted, and overwrite is disallowed. Always inspect third-party workflows and permitted hosts/actions before installing. The **catalog includes a local installed folder and a public JSON index**, not a hosted account marketplace. Community registry submission instructions are in [marketplace/README.md](marketplace/README.md).

## Local REST API

`h2a serve` exposes only `127.0.0.1`, not the internet. The dashboard uses an ephemeral `X-H2A-Token` API header and checks Host/Origin against DNS rebinding. Runs show step progress and offer cooperative cancellation; two simultaneous executions are allowed, with extra requests receiving HTTP 429. Use `h2a openapi --output openapi.json` or [API documentation](docs/API.md).

## Native Windows UI Automation (stable accessibility selectors)

Unlike screen coordinates, Windows UIA can address a control by its accessible name or automation ID. These actions are optional, and **do not require recording typed keys**. Windows must grant the required application accessibility permissions. On macOS/Linux, use pointer actions for now.

```bash
python -m pip install -e '.[accessibility]'
h2a inspect-desktop --window 'Untitled - Notepad'
```

Example desktop steps (replace window title / ID with your actual output):

```json
{"action":"ui_fill","windowTitle":"Untitled - Notepad","automationId":"15","value":"{{note}}"}
{"action":"ui_assert_text","windowTitle":"Untitled - Notepad","name":"Editor","text":"{{note}}","retries":2,"retryDelayMs":750}
```

The Windows UIA `ui_fill` action supports Unicode through the target's ValuePattern, without using clipboard or keystroke logging. Ambiguous/hidden controls fail closed. Password controls are not selectable.

## Local recurring schedules and cancellation

```bash
h2a plan create_invoice --data '{"customer_name":"Alex","amount":25}'
h2a schedule add create_invoice --every-minutes 60 --approve --data-file /absolute/private/inputs.json
h2a schedule list
h2a scheduler               # Foreground worker; stop with Ctrl+C
h2a schedule remove create_invoice
```

Scheduled input file values are **never saved in the registry or history**. On POSIX, input JSON files must be readable only by their owner (`chmod 600`). Schedule intervals are 1–10,080 minutes. Nothing runs in the background until the user starts `h2a scheduler` (or configures an OS service). The worker deliberately records no output values. For REST cancellation, use `POST /api/runs/{runId}/cancel` with the dashboard's token. Cancellation is cooperative and may take until the current GUI or ADB operation completes.

## Signed community packages

```bash
pip install -e '.[signing]'
h2a keygen --private ~/h2a-publisher.pem --public ~/h2a-publisher.pub.pem
chmod 600 ~/h2a-publisher.pem             # POSIX only
h2a pack create_invoice --publisher 'your-handle' --sign-key ~/h2a-publisher.pem --output create_invoice.h2a.zip
h2a verify create_invoice.h2a.zip --trust-key ~/h2a-publisher.pub.pem
h2a install create_invoice.h2a.zip --trust-key ~/h2a-publisher.pub.pem --approve --directory other_workflows
```

Do not commit private keys. A package can be cryptographically valid while its actions are untrustworthy: review permissions and hosts before approval. Unsigned v1 packages remain supported.

## Examples, tests and release state

- **Browser:** [`workflows/create_invoice.json`](workflows/create_invoice.json) — runnable against the fake invoice sandbox after starting `h2a serve`.
- **Desktop:** [`workflows/desktop_note.json`](workflows/desktop_note.json) — **illustrative coordinates only**; adjust positions for your own screen and editor before approving.
- **Android:** [`workflows/android_settings.json`](workflows/android_settings.json) — **illustrative device UI**; adapt displayed text to your phone before approving.
- Tests: `python -m pip install -e '.[dev]' && python -m pytest -q`
- Build: `python -m build`
- Security policy: [SECURITY.md](SECURITY.md); limitations and next features: [ROADMAP](docs/ROADMAP.md).

## License and contribution

Apache-2.0. Contributions and tests on real devices are especially welcome. [Contributing guide](CONTRIBUTING.md) · [Code of conduct](CODE_OF_CONDUCT.md) · [Architecture](docs/ARCHITECTURE.md) · [Issue tracker](https://github.com/karemfree1282-gif/human2api/issues).

**Help validate it: try the sandbox, report a reproducible bug, and contribute hardware acceptance results.**
