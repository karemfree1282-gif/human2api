# Signed workflow registry: operation and deployment

The included service stores publisher accounts, immutable versions, reviews and revocations in SQLite. It never runs uploaded workflows. There is **no prepopulated community, fake reviews, or automatic identity verification**. An operator independently verifies and enrolls a publisher's Ed25519 key. This establishes the registry's administrative trust relationship, not a guarantee that a workflow is safe.

## Local operation

```bash
h2a registry enroll alice --public-key alice.pub.pem --directory .h2a/registry
h2a registry serve --directory .h2a/registry
```

The enrollment token is shown once and stored only as a SHA-256 digest. At `http://127.0.0.1:8770`, a publisher enters that token and uploads a signed `.h2a.zip` plus a semantic version. Use `h2a pack ... --sign-key publisher.pem --release-version 1.0.0`; the submitted version must match the signed version. Both the signature and account key are required; checksum-only packages and impersonation fail.

Search is public. Reviews require another enrolled account; self-review is rejected and each account has one updatable rating per skill. Revoked account reviews disappear from aggregate ratings. Version uploads never overwrite earlier content. A publisher may yank a version; an operator may revoke the account.

```bash
h2a registry rotate-token alice --directory .h2a/registry
h2a registry revoke alice --directory .h2a/registry
h2a registry backup --file private-backup.sqlite3 --directory .h2a/registry
h2a registry restore --file private-backup.sqlite3 --directory restored-registry
```

Backup uses SQLite's consistent backup API and runs an integrity check. Restore requires a NEW destination and an operator-trusted backup; it does not overwrite a live service. Store backups encrypted off-host and test restores. Token rotation invalidates the old token immediately. Public signing-key changes require explicit re-enrollment rather than a silent key substitution.

## Install or upgrade

```bash
h2a registry-install alice invoice_skill 1.0.0 --origin https://registry.example.org --trust-key alice.pub.pem --approve
h2a registry-install alice invoice_skill 1.1.0 --origin https://registry.example.org --trust-key alice.pub.pem --approve --upgrade
```

Obtain the trusted public key independently. Upgrades require the same registry, publisher and pinned key, a strictly newer version, and an unchanged locally installed workflow. They create a revision backup. Edited local workflows are not silently overwritten. Review the new permissions/actions before approving; signatures do not replace review.

## HTTPS deployment

`deploy/compose.yml` runs a non-root registry behind Caddy with a persistent data volume. Only the proxy exposes public ports; the registry has a read-only image filesystem, bounded connections, limited memory/processes, dropped capabilities and a writable private data volume.

On a host you control, point an owned domain at it, set `H2A_DOMAIN`, and run:

```bash
H2A_DOMAIN=registry.example.org docker compose -f deploy/compose.yml up --build -d
```

This command provisions infrastructure only when YOU run it on an authorized host. It is not evidence that an online registry has already been deployed. HTTPS issuance requires reachable DNS and ports 80/443. Pin reviewed container image digests for production. Apply host security updates, external monitoring/rate controls and volume backup policies.

Use `docker compose -f deploy/compose.yml exec registry ...` for operator enrollment/backup. Place public keys through a temporary read-only mount; never copy publisher private signing keys into the service. Do not expose the localhost control API or Android bridge on this public host.

## API

- `GET /health`: service/version probe.
- `GET /v1/packages?q=...`: bounded public catalog.
- `GET /v1/packages/{publisher}/{name}/{version}`: signed ZIP bytes.
- `POST /v1/publish`: authenticated version and base64 ZIP.
- `POST /v1/yank`: authenticated name/version.
- `POST /v1/ratings`: authenticated publisher/name/stars.

API tokens go only in the `Authorization: Bearer` header, never URL query strings. Enrollment/revocation/backup/restore remain operator CLI functions, not anonymous web APIs.
