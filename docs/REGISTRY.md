# Ed25519 Signed Marketplace & Registry Specification

Every `.h2apkg` archive contains exactly two files (`manifest.json` and `workflow.json`) and is signed with the publisher's Ed25519 private key over `h2a-pkg-v1|<tool_id>|<version>|<publisher_id>|<workflow_sha256>`.

```json
{
  "schema": "h2a-package-manifest-v1",
  "tool_id": "invoice-exporter",
  "version": "1.0.0",
  "publisher_id": "acme_labs",
  "workflow_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
}
```
