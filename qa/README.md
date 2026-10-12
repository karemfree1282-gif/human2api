# Reproducible local acceptance

Run from the source checkout, with the declared development dependencies:

```sh
python scripts/complete.py --repair --native --android --output evidence/full
python qa/soak.py --requests 1000 --workers 16 --output evidence/soak.json
```

The completion command reports blocked gates honestly and exits nonzero for missing prerequisites or skipped tests. It does not change billing, approve device permissions, or manufacture installers. It never suppresses browser policy errors. The soak probe uses temporary local stores and synthetic data, not real accounts or public endpoints.

`tests/test_release_acceptance.py` exercises actual HTTP/TLS sockets, independently generated signing keys, concurrent immutable package publication, version-pinned installation/upgrades, backup/restore and explicit token revocation. Its TLS certificate is a short-lived, locally trusted test identity: passing it does **not** mean a public HTTPS deployment exists.

Registry race regressions deliberately trigger revocation/rotation between initial authentication and a write. The write must revalidate the token under its transaction lock. Identity and origin headers must be unique, including mixed-case duplicates.

The load probe records observed latency at a chosen concurrency; it is not a production capacity guarantee. It also verifies exclusive desktop leases, cooperative cancellation, lease release, and continued service health using a wait-only workflow. It does not interact with any actual desktop application.

Keep screenshots, keys, vaults, inputs and machine-specific logs private. Publish only sanitized summaries and hashes. Native and Android acceptance still requires appropriate OS/toolchains/devices; neither passing mocks nor a virtual test window is proof of physical-device support.
