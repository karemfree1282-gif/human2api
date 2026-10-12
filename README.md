<div align="center">
<img src="docs/assets/logo.svg" alt="Human2API" width="72" />

# Human2API

**Teach a task. Inspect its steps. Run it as an MCP tool or API.**

Browser · Windows UIA · macOS AX · Linux AT-SPI · Android companion

[![CI](https://github.com/karemfree1282-gif/human2api/actions/workflows/ci.yml/badge.svg)](https://github.com/karemfree1282-gif/human2api/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue)](LICENSE)

[Quick start](#quick-start) · [Arabic](docs/README_AR.md) · [Architecture](docs/ARCHITECTURE.md) · [Security](SECURITY.md) · [Acceptance](docs/ACCEPTANCE.md)
</div>

> **v0.4.1 integration release, not a production certification.** Core code and browser DOM behavior have local automated tests. Native hardware, Android APK execution and hosted deployment require their own acceptance evidence. GitHub Actions was independently confirmed blocked by an **account billing lock**, not by an executed test failure. See [issue #8](https://github.com/karemfree1282-gif/human2api/issues/8).

Human2API turns an explicitly recorded, reviewed workflow into reusable local automation. The core runs without a cloud account or AI model. Optional AI recovery sends bounded interface metadata only with explicit consent. It never executes model-generated code.

## Quick start

```bash
git clone https://github.com/karemfree1282-gif/human2api.git
cd human2api
python -m pip install -e '.[vault,signing]'
python -m playwright install chromium
h2a init
h2a serve
```

Open `http://127.0.0.1:8765`. The invoice sandbox at `/demo` uses fake data and never processes payments. Use **Visual editor** to create or reorder actions, define input variables, validate, and save with conflict detection and revision backups.

```bash
h2a check create_invoice
h2a plan create_invoice --data '{"customer_name":"Alex","amount":49.99}'
h2a run create_invoice --data '{"customer_name":"Alex","amount":49.99}' --approve
```

On Windows, use a UTF-8 JSON file with `--data-file inputs.json` to avoid shell quoting differences. Do not put real secrets into shell history.

## What is implemented

| Surface | Functions | Important boundary |
|---|---|---|
| Browser | DOM recording, unique selector fallback, tabs, nested stable iframes, assertions, downloads, strict request allowlist | Not every website, inaccessible canvas, or OS dialog is supported |
| Desktop | Pointer recording/replay, native UIA/AX/AT-SPI selectors, Unicode native text, smart editable placeholders | Needs an approved interactive OS accessibility session; device tests remain required |
| Android | ADB runner plus consent-based accessibility recording, Unicode text, scoped clicks/scrolling | Companion must be built, installed and explicitly armed on an authorized phone |
| Studio | Native webview launcher, visual builder, live progress, cancellation, schedules, revision-safe editing | Native packaging is built separately on each OS |
| Agents | Typed MCP tools, legacy initialization and 2026-07-28 discovery, progress, cancellation | Your MCP client must obtain human approval for writes |
| Privacy | Encrypted secret vault, redacted results, metadata-only journal, private artifacts, device locks | Not a complete desktop OS sandbox or perfect memory erasure |
| Sharing | Ed25519 signatures, pinned publisher keys, registry accounts, search, reviews, revocation, upgrades, backup/restore | Admin enrollment is not automatic real-world identity verification |
| Release | One-command repair/check/build reports, native/Android workflows, draft-only release artifacts | A blocked/skipped gate is never reported as successful |

## Record and reuse

```bash
h2a record https://example.org --name browser_task
python -m pip install -e '.[desktop,accessibility,studio]'
h2a record-desktop --name desktop_task --smart
h2a inspect-desktop --window 'Your exact application window'
h2a devices
h2a record-android --name guided_android
h2a studio
```

Smart desktop capture uses native selectors where possible and inserts placeholders for editable fields. It does **not** capture typed values. Pointer fallback depends on display layout. On Linux, install the distro AT-SPI Python binding and a compatible webview backend; see [platform setup](docs/PLATFORMS.md).

The Android companion source is in [`android-companion/`](android-companion/README.md). It records supported click/text-change/scroll events only after visible consent; text changes create required variables, not recorded values. Password controls are excluded. Its bridge is loopback-only, scoped to the selected app, and uses a rotating five-minute token with a STOP notification.

## Connect an AI agent

```json
{"mcpServers":{"human2api":{"command":"h2a","args":["mcp","--directory","/absolute/path/to/workflows"],"env":{"H2A_ALLOW_WRITE":"0"}}}}
```

Set `H2A_ALLOW_WRITE=1` only with client-side user approval. Enable `--heal-selectors` for unique semantic recovery and additionally `--ai-heal` for your explicitly configured OpenAI-compatible endpoint. AI suggestions never expand the approved application scope or silently overwrite workflows. Never automatically retry a failed write.

## Protect secrets and run batches

```bash
h2a vault init --file .h2a/secrets.vault
h2a vault set account_token --file .h2a/secrets.vault
h2a run my_workflow --vault .h2a/secrets.vault --secret token=account_token --approve
h2a batch create_invoice --file inputs.csv --approve
```

Master passwords and secret values are prompted without echo. Declare a secret input in the workflow before mapping it. Batch input rows are all validated before the first operation; execution stops on failure without silently repeating writes.

## Publish inspectable skills

```bash
h2a keygen --private publisher.pem --public publisher.pub.pem
h2a pack create_invoice --output invoice.h2a.zip --publisher my_publisher --sign-key publisher.pem --release-version 1.0.0
h2a verify invoice.h2a.zip --trust-key publisher.pub.pem
h2a registry serve
```

The included registry is a **real self-hosted service**, not a claim that a public instance is already running. It never executes uploaded workflows. Enrolled account tokens plus pinned package signatures are required to publish. See [registry operations and HTTPS deployment](docs/REGISTRY.md). Keys, vaults and backups must never be committed.

## Schedules and cancellation

```bash
h2a schedule add create_invoice --every-minutes 60 --data-file private-inputs.json --approve
h2a scheduler
```

The scheduler remains in the foreground. Recurring writes require explicit enrollment approval. Cancellation is cooperative: an already-issued native/ADB call can finish; neither cancellation nor an error implies rollback.

## One-command release assembly

```bash
python -m pip install -e '.[dev,vault,signing]'
h2a complete --repair
# Explicit optional installs/builds:
h2a complete --repair --bootstrap --native --android
```

The tool repairs deterministic generated schemas, validates workflow contracts, checks JavaScript/Python, runs the **unfiltered** test suite, builds and installs a fresh wheel, and emits a private machine-readable report. `--local-only` checks only the local component scope. Exit code **2** means failed or blocked evidence, including skipped tests. It does not manufacture code, unlock accounts, grant device permissions, or claim that mock tests are hardware tests.

Native distributions and Android debug APKs have build workflows. Published releases remain **drafts** until their release-gate jobs pass and maintainers review acceptance evidence. Signing/notarization requires owner-managed identities. [Release and acceptance procedure](docs/ACCEPTANCE.md).

Apache 2.0 · [Contributing](CONTRIBUTING.md) · [Security boundaries](SECURITY.md)

## Latest security and acceptance checks

The 0.4.1 patch rejects ambiguous HTTP headers and closes registry revocation/rotation write races. See [the reproducible QA procedure](qa/README.md) and run `python qa/soak.py --output evidence/soak.json` for synthetic loopback load checks. This is not physical-device, native-installer, or public-hosting certification.
