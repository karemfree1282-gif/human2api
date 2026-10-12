# Reproducible release acceptance

`h2a complete` is a bounded build/check orchestrator, **not a magic coding agent or a way to bypass platform restrictions**. It repairs deterministic generated schemas, executes actual commands and distinguishes passed, failed and externally blocked checks. It never edits tests to hide failures, pays bills, grants permissions or fabricates evidence.

## One command

From the source checkout:

```bash
h2a complete --repair
# Explicit dependency downloads and native/Android builds:
h2a complete --repair --bootstrap --native --android --evidence-dir evidence
```

Private reports/logs go under `.h2a/checks/<session>/`. Checks compile Python, validate JavaScript and contracts, run the full pytest suite, build a wheel, install it in a new directory and smoke-test the installed CLI outside the source checkout. Skipped tests are **blocked**, not green. Collection errors fail. `--local-only` never sets `releaseReady` true.

Release checks additionally inspect source-bound device receipts and hosted workflows for the published source. The public GitHub API receives no local code or credentials. Missing toolchains, unavailable services and stale evidence do not establish success. Reports are operator evidence, not independent certification.

## Physical devices

Use a synthetic workflow on a test application you control. End with an assertion of the actual result, not merely a click. Exercise recording, Unicode input, changed UI/recovery, ambiguous-control rejection, permission denial and cancellation. Test advertised display/OS variants.

```bash
python scripts/acceptance_probe.py windows-uia --workflow reviewed.json --data-file synthetic-inputs.json --output evidence --acknowledge-owned-test-app
```

Other targets: `macos-ax`, `linux-atspi`, `android-companion`. Run on the corresponding system; Android requires an explicitly armed companion. Receipts bind a source digest, assertion count, OS data and workflow hash without retaining inputs/result text. A receipt is a minimum gate, not exhaustive compatibility proof. Never create receipts for mocked devices.

## Distribution and deployment

Build native bundles on each target OS with `scripts/build_native.py`, Android with `scripts/build_android.py`. Missing toolchains fail; no manifest is presented as an APK. OS signing needs owner-managed identities. Debug APKs and unsigned bundles are not production-signed releases. Required CI jobs must succeed before draft release assembly.

For the registry, verify real HTTPS, enrollment/publishing/revocation, rejection of untrusted packages, fresh-client installation, upgrades and backup/restore. The operator receipt `evidence/registry-deployment.json` must contain the matching `sourceDigest` and true `httpsVerified`, `backupRestoreVerified`, `publisherLifecycleVerified` fields. Never set these for an unhosted demo. Retain underlying operational evidence securely.

## External gates in this environment

- GitHub reports an account billing lock. The owner must resolve it or contact support. Changing runner labels or disabling checks does not fix it.
- Windows/macOS hardware and the Android SDK/device are not present here; mocked contracts are not physical acceptance.
- Managed Chromium blocks URL navigation. Real DOM/UI and local HTTP tests run, but four URL end-to-end tests are blocked. CI fails instead of skipping when its required browser cannot execute.
- Hosting/DNS and OS-signing credentials require an authorized operator. No hosted URL or signing identity is fabricated.

Report successful local evidence alongside blocked gates, not a misleading completion percentage.
