# Human2API workflow community catalog

**Currently a local verified-package directory**, not a hosted marketplace or an official list of trusted publishers.

## Submit an example

1. Use non-production demo accounts, deterministic screenshots and editable input placeholders. Never commit secrets, cookies, device serials or private URLs.
2. Validate with `h2a check NAME`, run a test in a sandbox, and `h2a pack NAME --output catalog/NAME.h2a.zip`.
3. Open a pull request with the JSON workflow in `examples/community/`, steps to reproduce it, expected target OS/browser/app versions, and a short screen recording with no personal data.
4. Maintainers can include reviewed packages in the local catalog. A SHA-256 is an integrity check **not** a signature. Automated trust/reputation ratings are not implemented.

## License

Examples must have appropriate redistribution permission. Do not use published workflows to access accounts or services without authorization.
