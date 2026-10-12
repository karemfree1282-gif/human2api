# Workflow sharing

A static community JSON index and a separately runnable registry are included. The index is not identity verification. The registry has publisher accounts, immutable versions, search, reviews, revocation and backup/restore, but needs operator enrollment and actual HTTPS hosting. No invented users/reviews or hosted-service claims.

See [operations](../docs/REGISTRY.md) and [security](../SECURITY.md).

```bash
h2a keygen --private publisher.pem --public publisher.pub.pem
h2a pack reviewed_skill --output reviewed.h2a.zip --publisher alice --sign-key publisher.pem --release-version 1.0.0
h2a verify reviewed.h2a.zip --trust-key publisher.pub.pem
```

Keep private keys outside source control. A release's submitted version must match its signed version. Keys obtained only from the untrusted package are not independent trust anchors.

Community examples must use synthetic data, authorized accounts, clear permissions, reproducible assertions and redistribution-compatible licensing. Submit inspectable JSON and target app/OS versions for review. Checksums establish integrity, not trust. No executable archive attachments or unauthorized automation.
