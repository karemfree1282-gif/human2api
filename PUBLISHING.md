# Publishing & Release Guide

1. Execute `python3 scripts/complete.py --repair` to run all tests, validate JSON schemas/docs, and build distribution artifacts in `dist/`.
2. Verify `dist/SHA256SUMS.txt` and `.h2a/checks/latest/verification_report.html`.
3. Sign Marketplace packages with `h2a keygen` and `h2a publish`.
4. Push verified commits and tags via `python3 scripts/publish_github.py`.
