# Roadmap

We prioritize security, reliability, and things ordinary users can actually verify. These features are **plans, not shipping capabilities**.

## v0.1 - Browser automation kernel (current)

- [x] JSON workflow schema / strict validation
- [x] Browser event recorder (single tab)
- [x] Dynamic named input variables, no saved form values
- [x] Replay / selector fallback / assertions / downloads
- [x] Local dashboard / OpenAPI / MCP stdio
- [x] Apache-2.0 license / project governance / CI suite

## v0.2 - Better recording (good first issues)

- [ ] End-to-end cross-browser CI (Firefox, WebKit) and Windows/macOS CI
- [ ] Record navigation and textarea blur edge cases
- [ ] Record keyboard shortcuts and file upload fixtures safely
- [ ] Pause, resume and inspect before saving
- [ ] Semantic locator strategies using accessible roles and labels
- [ ] Add a direct API token workflow outside the local dashboard
- [ ] Improve input type inference for `number` and `date`

## v0.3 - More durable workflows

- [ ] Self-healing selector suggestions (never silently execute changed operations)
- [ ] Workflow diff/approval UI
- [ ] Per-action approvals and dry-run preview
- [ ] Encrypted opt-in session profiles
- [ ] Browser trace viewer and automatic replay reports

## v0.4+ - Beyond the browser

- [ ] Cross-platform desktop automation via audited OS accessibility APIs
- [ ] Optional Android accessibility bridge
- [ ] Signed workflow registry + provenance, versions and reproducible checks
- [ ] Community templates with verified tests and threat review
- [ ] Optional model providers for proposing (not blindly applying) recovery

## Open questions

1. How should workflows express accessibility selectors without coupling to one browser?
2. How do we capture navigation robustly when a site involves third-party SSO?
3. What should an audit-friendly permission format look like at step granularity?
4. How can we sandbox browser workflows strongly enough to accept third-party templates?

Open an issue using the included templates if you want to help.
