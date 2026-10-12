# Building and publishing

Publishing source is not verified deployment. Run `h2a complete --repair` and inspect every gate. Dependency downloads require `--bootstrap`; native/Android builds require their toolchains and explicit flags.

The current GitHub account has a confirmed billing runner lock (issue #8). Resolve it in account settings/support, then rerun CI. Do not suppress tests or change payment settings through a source script.

After local, hosted and physical acceptance, create a reviewed version tag. The release workflow runs required jobs, validates tag/version agreement and creates a **draft**. Check signatures, hashes and acceptance before publishing it. Debug/unsigned artifacts are not production-signed downloads.

GitHub Pages hosts static docs. The workflow registry is a separate service deployed with `deploy/compose.yml` to an authorized host. Validate TLS, enrollment and recovery. See `docs/REGISTRY.md` and `docs/ACCEPTANCE.md`.

The old `scripts/publish_github.py` bootstraps repositories; it is not billing resolution or release certification. This repository already exists as `karemfree1282-gif/human2api`; preserve its history during updates.
