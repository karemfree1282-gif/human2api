# Frequently asked questions

**Is Human2API an autonomous all-app AI agent?** No. It is an inspectable task recorder and deterministic runner. Browser selector suggestions may optionally be produced by an external AI model with explicit consent, but the project does not claim self-healing for every UI or app.

**Does it support desktop applications and Android?** The v0.2 developer preview has optional PyAutoGUI desktop automation and ADB Android automation, exposed through CLI/MCP/REST, with mocked unit tests. The native app/device acceptance-test matrix is not complete. The desktop recorder captures pointer actions only; Android uses a guided command recorder.

**Does it save my passwords or what I type while recording?** The browser recorder discards form values; the desktop recorder never captures keys or clipboard contents; the Android guided recorder saves required input placeholders, not demonstrated values. CSS selector metadata, URLs and UI labels may still reveal personal information. Review workflow files before sharing.

**Does it send my data to a cloud?** No telemetry or automatic cloud sync. Target websites naturally receive traffic. Opt-in AI selector healing sends limited interactive element metadata to your configured AI endpoint; it is off by default.

**Does the project include a hosted public marketplace?** No, only a local verifiable package catalog. Checksums are not identity signatures, and installing third-party workflows needs explicit approval.

**Will it operate my banking or payment app safely?** Do not use it on high-stakes accounts or production data until you have validated every action and target-specific security properties.

**Can I expose the REST API to the internet?** No. It is intended for loopback access from a trusted desktop session only.

**Why are some tests skipped?** The current development environment blocks Playwright navigation to local web URLs. DOM action tests and mocked platform tests run, but networked browser E2E and real-device tests must run on an unrestricted test host or CI runner.

**How can I help?** Run a reproducible task on real Windows/macOS/Linux or Android hardware, report environment and versions, and submit bug fixes/tests via the [contribution guide](../CONTRIBUTING.md).
