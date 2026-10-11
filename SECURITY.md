# Security policy

**Status:** v0.1 alpha. No public vulnerability disclosure channel is configured beyond GitHub private vulnerability reporting (if enabled by the repository owner). Do not post exploit details in public issues.

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
| 0.1.x | Best effort during alpha |
