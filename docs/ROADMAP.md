# Release status and roadmap

As of v0.2, this is an **open-source developer preview**. Features below are not claimed as complete until actually tested.

## Implemented and unit-tested

- Backward-compatible inspectable workflow JSON
- Browser recorder: DOM clicks, form fields, checkbox/select; cross-tab and first-level iframe support (stable iframe ID/name)
- Browser runner: Playwright, screenshots, downloads, tab switching, explicit host allowlist, fallback selectors, assertions
- Desktop runner: mouse and keyboard actions, screen capture and optional OpenCV image assertion; optional mouse-only desktop recorder
- Android runner: ADB tap/swipe/text/key events, UIAutomator text selectors, screenshot; interactive Android teaching wizard
- CLI, ephemeral-auth loopback REST API and typed MCP tools for all targets
- Optional local semantic selector healing; explicitly approved AI selector advice via compatible model endpoint
- Package packing, checksum verification, manual approval installation, local catalog and HTTPS read-only remote index with SHA-256-pinned downloads
- Metadata-only local SQLite run journal with 30-day retention, plus protected REST history endpoint
- Self-contained fake invoice demo and CI test suite with mocked device backends

## Integration validation still needed

- Real-world Windows/macOS/Linux UX recording and replay; coordinate/keyboard differences; native accessibility selectors
- Real Android phones across OEM versions; Unicode text, complex app UI, dialogs, multiple display modes
- Browser multi-tab and iframe scenarios with various modern sites and authenticated flows
- Fail/retry handling for transient network issues; history now persists metadata only
- Test/enable GitHub Pages deployment after GitHub Actions settings and runner availability are confirmed
- Real-user permission prompts in MCP clients

## Later major initiatives

- Native accessibility tree-based desktop recorder rather than only pointer replay
- Android companion AccessibilityService for consent-based native event capture (no unrequested keylogging)
- Offline computer vision fallback with local models for desktop/mobile
- Signed publisher identities and trusted online marketplace
- Cloud sync, team RBAC, scheduling, audit events and encrypted credentials

We do not claim 'automate any app flawlessly'. That is an aspiration requiring much more hardware validation and engineering.
