# Frequently Asked Questions (FAQ)

### Does Human2API require an OpenAI or cloud API key?
No. Recording, replay, REST API, MCP server, Visual Studio, and Tiers 1–3 of Self-Healing run 100% locally and free without any API key.

### How are passwords handled during recording?
Fields with `type="password"`, `isPassword=true`, or sensitive names (`password`, `token`, `api_key`, `secret`, `cvv`, `otp`, `pin`) are automatically replaced with `${secret:VAR_NAME}` and stored only inside the encrypted `AES-256-GCM` vault.
