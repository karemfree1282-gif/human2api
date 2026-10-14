# Reproducible Release Acceptance (v0.5.0)

Run the single verification command from the repository root:

```bash
python3 scripts/complete.py --repair
```

This command:
1. Inspects runtime dependencies and platform build toolchains.
2. Validates `schemas/workflow.schema.json`, all workflow examples, and all fenced JSON blocks in documentation.
3. Executes the complete automated test suite (Unit, Integration, Real Chromium Browser E2E, Studio UI Browser E2E, Live Linux GTK3/ATK Desktop E2E, Windows/macOS/Android adapters, 4-Tier Self-Healing, Marketplace HTTPS/TLS, Security Regressions, and Load/Soak tests).
4. Builds `human2api-0.5.0-py3-none-any.whl`, `human2api-0.5.0.tar.gz`, `h2a-0.5.0-linux-standalone.pyz`, and `human2api_0.5.0_all.deb`, computes `SHA256SUMS.txt`, and smoke-tests the Wheel in an isolated temporary directory.
5. Writes `.h2a/checks/latest/verification_report.json` and `.h2a/checks/latest/verification_report.html`.
