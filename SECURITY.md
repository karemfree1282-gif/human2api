# Security model and reporting

Human2API automates user-approved applications. A valid workflow, signature or passing unit test is **not** proof that automation is harmless. Review source, permissions, destinations, inputs and assertions before sensitive runs. Use only accounts and devices you are authorized to control.

## Isolation and approvals

The local REST service binds to loopback, validates Host/Origin, uses an unpredictable per-server token, rejects ambiguous request framing and bounds sizes/concurrent clients. Do not expose it through a tunnel or reverse proxy. The separate registry service supports HTTPS deployment and never executes uploaded workflows.

Write workflows require explicit permission. MCP clients must obtain human approval before setting `H2A_ALLOW_WRITE=1`; the server does not provide a separate consent dialog. Creating a recurring schedule grants permission for its later runs. Even a read-classified browser action may have server-side effects: use approved test accounts and hosts.

Browser contexts are separate from ordinary browser profiles. `networkPolicy: "strict"` restricts intercepted HTTP requests to allowed hosts and blocks service workers/WebSockets. It is not a substitute for an OS/container egress firewall or an audit of third-party page code. Navigation-only mode allows subresource requests and is not a network sandbox.

Desktop actions execute in the logged-in OS session, not an OS sandbox. Native controls must be uniquely resolvable, visible, enabled and non-password. Pointer actions remain focus/resolution-dependent. Cancellation is cooperative, not an instant interruption or rollback of arbitrary OS calls. Cross-process leases prevent cooperating Human2API processes from controlling the same device concurrently, not another application or human from changing it.

## Recording and secrets

Recorders replace typed values with variables rather than capturing input contents, keys or clipboard data. Android requires explicit package-scoped recording/arming, a visible stop notification and a short-lived loopback token; stopping revokes it. Password controls are excluded. Opaque/inaccessible UI may not be recordable. IDs, labels, window titles and URLs can still identify people or systems: inspect every export.

Vaults use authenticated AES-256-GCM and scrypt with random salts/nonces. Passphrases are prompted invisibly and never stored. Stale concurrent writes are rejected. Decrypted values exist in process memory; Python cannot guarantee secure erasure or defend against a compromised local account. Use a strong unique passphrase and OS disk encryption. POSIX files are owner-only; protect Windows profile/vault directories with appropriate ACLs. This is not a multi-user secrets server.

Persistent history stores status metadata, not inputs or result text. In-memory results are bounded and expire. Mark secret inputs explicitly: redaction cannot identify every transformed secret. Screenshots/downloads for workflows with secrets require separate `allowSensitiveArtifacts: true` permission. Private output directories still need operator retention/deletion policies. Never commit tokens, vaults, cookies, real input files or private signing keys.

## Recovery and retries

Remote AI recovery is OFF by default and requires per-run consent. Sanitized metadata goes only to an explicitly configured HTTPS or loopback provider; labels can still identify people. Metadata is untrusted data, not instructions. Suggestions select only existing controls, re-resolved uniquely inside the original host/window/package scope. They cannot introduce code or silently rewrite workflows. Ambiguity fails closed. Only bounded read checks retry; uncertain mutations stop.

## Packages and registry

Packages contain exactly two JSON files. Executables, archive traversal, symlinks and excessive sizes are rejected. Legacy v1 checksums prove integrity only. Ed25519 v2 installation pins an independently obtained publisher key. Registry publishing also requires an enrolled account token and a signed `releaseVersion`; an old signed package cannot be relabeled as a new release. Signatures prove possession of a key, not safety or legal identity.

The registry hashes tokens, keeps immutable versions, supports revocation/yanking, records administrative audit events and uses transactional SQLite storage. Operators independently verify publishers before enrollment. TLS, encrypted off-host backups, patching, monitoring and abuse protection are deployment responsibilities. Restoring an attacker-controlled database is not safe. Public registry routes are separate from the privileged runner.

## Release status and reporting

Native adapters/Android need physical-platform acceptance beyond mocked contracts. Native bundles are unsigned until owner-managed signing/notarization is configured. Checksums do not certify an OS publisher. GitHub Actions currently has an account billing lock; source patches cannot remove it.

Use GitHub private vulnerability reporting if enabled. Otherwise ask for a private contact in an issue without posting exploit payloads, credentials or user data. No response-time SLA or independent security certification is currently promised.
