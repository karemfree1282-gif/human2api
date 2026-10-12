# Capability and verification status - v0.4.0

This release adds implementation, integration tests and release tooling, not universal-app or hardware certification.

| Area | Implemented | Evidence still required |
| --- | --- | --- |
| Browser | Recording, unique selectors, parameterized input, nested stable frames, tabs, strict-host option, assertions and recovery | Four URL E2E tests outside managed-browser restrictions; representative authenticated sites |
| Desktop | UIA / macOS AX / Linux AT-SPI, smart pointer capture, Unicode native text and scoped recovery | Real recording/replay and display/permission cases on each OS |
| Android | Consent-scoped AccessibilityService companion, STOP notification, native selectors, Unicode input and ADB bridge | SDK build/lint and actual phones; opaque UI remains outside guaranteed support |
| Interfaces | CLI, local REST, modern/legacy MCP, visual editor and optional native Studio | Native installers and actual MCP approval UX |
| Safety | Vault, private metadata/artifacts, redaction, CAS editing, device leases, bounded cancellation/retries | Independent review, real OS interruption tests and deployment hardening |
| Sharing | Version-bound signatures, pinned-key upgrades, publisher accounts, reviews, revocation and backup/restore | Operator enrollment and real HTTPS service acceptance |
| Release | One-command checks, isolated wheel smoke, native/Android builds and draft-only releases | Billing unlock, green required hosted workflows and OS signing |

## Priorities

Resolve the billing lock and obtain real runner execution. Run platform acceptance and compile distributions with the supplied scripts. Deploy the independent registry to an authorized host and validate HTTPS/recovery. Expand compatibility using reproducible reports and synthetic examples.

## Deliberate boundaries

No silent keylogging, credential collection, arbitrary shell steps, automatic approval, fake reviews or safety claims from signatures. Pointer capture does not infer every human intention. Protected apps, opaque canvases, security dialogs and inaccessible controls may require another approved integration.

Enterprise SSO, team billing and multi-tenant execution are separate initiatives, not hidden dependencies of the local tool. See [acceptance](ACCEPTANCE.md), [platforms](PLATFORMS.md) and [security](../SECURITY.md).
