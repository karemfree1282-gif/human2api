# Human2API workflow community catalog

**Currently a local verified-package directory**, not a hosted marketplace or an official list of trusted publishers.

## Submit an example

1. Use non-production demo accounts, deterministic screenshots and editable input placeholders. Never commit secrets, cookies, device serials or private URLs.
2. Validate with `h2a check NAME`, run a test in a sandbox, and `h2a pack NAME --output catalog/NAME.h2a.zip`.
3. Open a pull request with the JSON workflow in `examples/community/`, steps to reproduce it, expected target OS/browser/app versions, and a short screen recording with no personal data.
4. Maintainers can include reviewed packages in the local catalog. A SHA-256 is an integrity check **not** a signature. Automated trust/reputation ratings are not implemented.

## License

Examples must have appropriate redistribution permission. Do not use published workflows to access accounts or services without authorization.

## Public read-only index (new)

The repository hosts a versioned static JSON index at [`marketplace/index.json`](index.json). You can browse it directly on GitHub, or fetch it through HTTPS:

```bash
h2a catalog --remote
# Read the workflow source first, then:
h2a install-remote create_invoice --approve --directory my_other_workflows
```

`install-remote` first checks the published package URL against the pinned SHA-256 in the HTTPS index, verifies the internal workflow digest, validates permitted actions, and refuses to overwrite an existing workflow. You are responsible for reviewing package code, publishers and permissions. Anyone controlling the remote index can replace both the package and its hash; this is **not a signed trust model** and there is no review/rating login system.
