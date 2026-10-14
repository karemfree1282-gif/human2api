# Security Model and Reporting

Human2API automates user-approved applications. A valid workflow, signature, or passing unit test is not proof that automation is harmless. Always review source, permissions, allowed hosts/packages, inputs, and assertions before sensitive runs.

## Local REST API Isolation & Approvals

- Binds strictly to loopback (`127.0.0.1` or `127.0.0.2`).
- Rejects duplicate HTTP identity/framing headers (`Host`, `Origin`, `Authorization`, `X-H2A-Token`, `Content-Length`, `Transfer-Encoding`).
- Enforces `Host` and `Origin` allowlists to block DNS Rebinding and cross-site CSRF.
- Requires Bearer / `X-H2A-Token` authentication, enforces token-bucket rate limits and request body size caps.
- Mutating (`write`) workflows require explicit write approval (`allow_write=True` or `H2A_ALLOW_WRITE=1`).

## Secrets, Redaction & Self-Healing Boundaries

- Password and sensitive fields are replaced with `${secret:VAR}` during recording; raw passwords are never written to workflow files or logs.
- `SecretVault` uses authenticated `AES-256-GCM` encryption with `scrypt` key derivation (`n=2^14, r=8, p=1`), random 16-byte salts, 12-byte nonces, and automatic inactivity lock.
- Self-Healing never executes AI-generated code, never sends passwords or user files externally, and never retries a non-idempotent write step that already dispatched.
- Packages (`.h2apkg`) contain strictly `manifest.json` and `workflow.json`, signed with Ed25519, and reject ZIP Slip, symlinks, executables, and oversized entries.
