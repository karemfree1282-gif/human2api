# Show HN post (draft — do not publish until repo URL and demo work)

**Title:** Show HN: Human2API – Record browser tasks and expose them as MCP tools

I built an open-source tool for a problem I kept seeing with AI agents: lots of everyday software lacks an API for the action you want.

Human2API records clicks and form changes in a Chromium session, converts values to runtime parameters (without saving what you typed), and writes a plain JSON workflow. The runner can replay the workflow, verify text on the page, extract output and download files. Each workflow becomes a typed MCP tool or a local REST endpoint.

The included fake invoice demo takes a couple of minutes to try. No external model key or cloud account is needed. It's a Python/Playwright alpha under Apache-2.0.

Limitations worth calling out: only one main browser tab, no desktop support, no automatic AI self-healing, and the host allowlist is not a full network sandbox. I'd love feedback on action verification, selector durability, and sensible default permissions for agent tools.

GitHub: https://github.com/karemfree1282-gif/human2api
Demo: https://karemfree1282-gif.github.io/human2api/
