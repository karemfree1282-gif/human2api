# Security policy

**Status:** v0.2 developer preview. No public vulnerability disclosure channel is configured beyond GitHub private vulnerability reporting (if enabled by the repository owner). Do not post exploit details in public issues.

## Report privately

Once the public repository is published, use its **Security > Report a vulnerability** option if GitHub private reporting is enabled. If it is not enabled, open a neutral issue asking the maintainer for a private contact channel without sharing details.

## Important limitations

- Workflows can click destructive buttons, submit forms, and navigate to sensitive pages. Review workflows before executing and prefer test accounts.
- Values typed during a recording are discarded. **Selectors, attribute names, and start URLs may still contain confidential tokens or personal information.** Review exported JSON before committing.
- A workflow with an embedded URL query string can expose secrets. The recorder strips query strings and fragments from its initial URL. Manually edited workflow URLs are not automatically scrubbed.
- Browser route navigation allowlists are a guardrail, **not a full network isolation boundary**. Browser Javascript and subresource fetches can contact other hosts.
- The local dashboard is not designed to run on public internet hosts. It binds to 127.0.0.1, requires an ephemeral token and validates Host and Origin.
- The MCP server does not display user approval prompts. `H2A_ALLOW_WRITE=1` authorizes write actions when requested by the connected agent. MCP client permissions remain essential.
- Exported workflow files are unencrypted. Treat local filesystem and `runs/` as private.
- No arbitrary code execution from workflow JSON is supported, but Playwright executes the target page's own Javascript in its browser context.

## Threat model to improve

A malicious page could change the selector target, trick a workflow into clicking unexpected controls, or abuse browser network access. We want signed verified community workflows, opt-in session isolation, stronger network boundaries and step-level consent before recommending use in high-stakes contexts.

## Supported versions

| Version | Security fixes |
| --- | --- |
| 0.1.x | Legacy alpha, limited maintenance |
| 0.2.x | Best-effort fixes during developer preview |

## v0.2 platform threat model

- **Desktop:** PyAutoGUI operates in the user's active GUI session. Authorize only on your own machine and review every coordinate/shortcut. Moving the pointer to the upper-left triggers the PyAutoGUI failsafe. The pointer-only recorder never captures keystrokes/passwords; runtime `type_text` values may still be visible to desktop programs.
- **Android:** ADB works only with an authorized connected device. The adapter uses fixed argument arrays (no host shell), a strict device serial, exact UI text matching and an allowlisted subset of keys. `adb shell input text` supports only restricted ASCII and may expose arguments through device/system diagnostics. Use a test device and account.
- **AI selector recovery:** OFF by default. With explicit opt-in, up to 70 element metadata records can leave your machine for the configured OpenAI-compatible endpoint; IDs and aria labels may contain identifying information. The model can only return a CSS selector, checked for a single visible match, and never silently changes source workflows. This feature is not suited to confidential apps without an approved provider/data-policy review.
- **Community packages:** A `.h2a.zip` has exactly two JSON files. Sha256 guarantees only integrity, **not** author identity or safety. Explicitly review permissions, hosts, and steps prior to installing and running. No executable bundle payloads are allowed.
- **General:** UI navigation allowlists are not a sandbox for page subresources. Do not expose the loopback REST server via tunneling or reverse proxies. There is no cloud authentication, secret vault, native mobile accessibility service, or signed marketplace in this release.
