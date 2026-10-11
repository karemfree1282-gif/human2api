# Human2API workflow community catalog

**Currently a local verified-package directory**, not a hosted marketplace or an official list of trusted publishers.

## Submit an example

1. Use non-production demo accounts, deterministic screenshots and editable input placeholders. Never commit secrets, cookies, device serials or private URLs.
2. Validate with `h2a check NAME`, run a test in a sandbox, and `h2a pack NAME --output catalog/NAME.h2a.zip`.
3. Open a pull request with the JSON workflow in `examples/community/`, steps to reproduce it, expected target OS/browser/app versions, and a short screen recording with no personal data.
4. Maintainers can include reviewed packages in the local catalog. A SHA-256 is an integrity check **not** a signature. Automated trust/reputation ratings are not implemented.

## License

Examples must have appropriate redistribution permission. Do not use published workflows to access accounts or services without authorization.

## Signed package v2 (Ed25519)

Publisher workflow authors may use `h2a keygen`, then sign `h2a pack ... --sign-key private.pem`. Users who obtained the publisher's public key via a trusted independent channel can use `h2a verify ... --trust-key publisher-public.pem` or `h2a install ... --trust-key publisher-public.pem --approve`. The signature binds publisher metadata and the checksum of the workflow JSON. A signature never means workflows are safe by itself. Unsigned v1 packages remain supported for backward compatibility. The public index currently lists URLs and hashes, not verified publisher accounts.
