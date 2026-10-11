# Contributing to Human2API

We want small, testable PRs that improve trustworthiness. All skill levels are welcome.

## Set up

```bash
python -m pip install -e '.[dev]'
python -m playwright install chromium
python -m pytest -q
```

Use a new branch for your change. Keep browser tests deterministic and run them against the bundled fake invoice demo, not third-party websites. Never commit recorded credentials or real people's data.

## Submitting a PR

1. Describe the exact user problem and expected behavior.
2. Add/adjust tests for new actions and security boundaries.
3. Run the test suite, and state any skipped or environment-blocked tests.
4. Update README, SECURITY and docs/ROADMAP where appropriate.
5. Make sure your change does not record or persist user form values.

We particularly need accessibility selector strategies, safer action verification, platform testing, documentation translations, and a reproducible permission model.

## Conduct and licensing

Be respectful and constructive; see CODE_OF_CONDUCT.md. Contributions are licensed under Apache-2.0. By submitting code you confirm you have the rights to contribute it.
