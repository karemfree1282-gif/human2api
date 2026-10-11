# Release status and roadmap

As of v0.3, this is an **open-source developer preview**. Features below are not claimed as complete until actually tested.

## Implemented and unit-tested

- Backward-compatible inspectable workflow JSON
- Browser recorder: DOM clicks, form fields, checkbox/select; cross-tab and first-level iframe support (stable iframe ID/name)
- Browser runner: Playwright, screenshots, downloads, tab switching, explicit host allowlist, fallback selectors, assertions
- Desktop runner: mouse and keyboard actions, screen capture and optional OpenCV image assertion; optional mouse-only desktop recorder
- Android runner: ADB tap/swipe/text/key events, UIAutomator text selectors, screenshot; interactive Android teaching wizard
- CLI, ephemeral-auth loopback REST API and typed MCP tools for all targets
- Optional local semantic selector healing; explicitly approved AI selector advice via compatible model endpoint
- Package packing, checksum verification, optional Ed25519 signing with pinned public keys, manual approval installation and local/public JSON catalog
- Self-contained fake invoice demo and CI test suite with mocked device backends
- Native Windows UIA named/automation-ID selectors for click/fill/assert/extract; Unicode text through ValuePattern
- Cooperative per-run cancellation, live step status, bounded local concurrency and private metadata history
- Bounded retries for read-only UI checks (never duplicate mutations)
- Opt-in local recurring job scheduler using permission-checked input files (worker runs in foreground)

## Integration validation still needed

- Real-world Windows/macOS/Linux UX recording and replay; Windows UIA integration requires real hardware validation; macOS/Linux native accessibility selectors still not implemented
- Real Android phones across OEM versions; Unicode text, complex app UI, dialogs, multiple display modes
- Browser multi-tab and iframe scenarios with various modern sites and authenticated flows
- End-to-end operator-tested cancellation for long-running native UI/ADB calls; current cancellation is cooperative
- Test/enable GitHub Pages deployment after GitHub Actions settings and runner availability are confirmed
- Real-user permission prompts in MCP clients

## Later major initiatives

- Native accessibility tree-based desktop recorder rather than only pointer replay
- Android companion AccessibilityService for consent-based native event capture (no unrequested keylogging)
- Offline computer vision fallback with local models for desktop/mobile
- Hosted identity-verified publisher accounts and trusted online marketplace (cryptographic package signatures and public index exist, but no hosted accounts)
- Cloud sync, team RBAC, scheduling, audit events and encrypted credentials

We do not claim 'automate any app flawlessly'. That is an aspiration requiring much more hardware validation and engineering.
