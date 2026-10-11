# Launch kit: distribution without spam

Do not call this project a universal desktop tool or an autonomous self-healing agent yet. Ship the working v0.1 story: record a browser task, replace inputs, verify output and expose MCP/REST.

## Day 0 (publish)

- [ ] Create a public GitHub repository and push all source files, tests, license and docs.
- [ ] Set repo description, topics, Issues, Discussions and the homepage link.
- [ ] Enable GitHub Pages: Settings > Pages > Deploy from a branch > main /docs.
- [ ] Ensure CI is green and install instructions work from a clean environment.
- [ ] Tag v0.1.0 and generate release after CI passes.
- [ ] Record a 30-45 second screencast of the real, local invoice demo (no fake AI claims).
- [ ] Attach screencast/GIF to README near the hero, after verifying permissions/privacy.

## Days 1-7 (feedback)

- [ ] Post one accurate Show HN launch (draft in show-hn.md).
- [ ] Share a short, relevant Reddit post where self-promotion is permitted (draft in reddit.md).
- [ ] Ask 10 automation developers to test the demo and file real bugs; do not buy stars.
- [ ] Convert verified feedback into labelled good-first-issue opportunities.
- [ ] Publish an architecture/security blog entry about why values are never recorded.

## Days 8-30 (community)

- [ ] Add short docs for Claude Desktop, VS Code, Cursor and compatible MCP clients.
- [ ] Create a reproducible example gallery using fake datasets only.
- [ ] Publish every milestone with honest changelog and failing-test disclosures.
- [ ] Make issue discussions friendly and review contributors quickly.
- [ ] Consider Python package distribution once CI/tests/release packaging are verified.

## Trust metrics, not vanity metrics

Track successful first-run attempts, reproduction rate across sites, open issue response time, contributed tests, active contributors and actual installations. GitHub stars are a useful signal, not the product.

## Pre-launch truth checklist

- [ ] Check that the advertised URL resolves and shows the intended README and license.
- [ ] Verify CI results in the public repository, not just on a development machine.
- [ ] Confirm the Pages site is publicly reachable, with correct social preview.
- [ ] Do not claim Windows/macOS/Android support without validating the exact workflow on those systems.
- [ ] Only post to communities where a technical Show/Launch is permitted, from an account you control.
- [ ] Distinguish real recorder video from conceptual features on the roadmap.
- [ ] Do not mass-DM people, buy stars, or manufacture engagement.

## Relaunch guardrails for v0.2

- [ ] Run `python -m pytest -q` on all supported Python versions.
- [ ] Run a full end-to-end fake-invoice browser test on an unrestricted machine.
- [ ] Verify native Windows/macOS/Linux pointer replay and Android ADB workflows on real hardware before declaring the corresponding integrations stable.
- [ ] Confirm GitHub Actions green (CI, CodeQL, Pages) and investigate any repository/account runner restrictions.
- [ ] Do not announce a fully autonomous self-healing agent or signed online marketplace; those are **not implemented**.
- [ ] Record a genuine short demonstration (no fake UI interaction and no private user data).
- [ ] Publish community posts manually and respectfully; never mass-post or claim number-one status.
