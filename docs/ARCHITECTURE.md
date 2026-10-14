# Human2API System Architecture (v0.5.0)

1. **Recorder Layer (`recorder.py`)**: Captures user actions from Browser DOM, Desktop Accessibility trees, or Android `AccessibilityService`, strips passwords (`${secret:...}`), parameterizes inputs (`${input:...}`), and emits ranked fallback selectors.
2. **Execution & Runner Layer (`runner.py`, `execution.py`, `desktop.py`, `native.py`, `android.py`)**: Executes steps with strict `allowedHosts` / `allowedApps` / `allowedPackages` checks, multi-tab and nested `iframe` support, cooperative/immediate cancellation (`CancellationToken`), and post-condition assertions.
3. **4-Tier Self-Healing Layer (`healing.py`)**:
   - Tier 1: Primary selector.
   - Tier 2: Recorded fallback selectors.
   - Tier 3: Semantic Accessibility role/name/landmark similarity with ambiguity rejection.
   - Tier 4: Optional consent-gated AI candidate advisor (never executes model code, never retries non-idempotent writes).
4. **Security & Trust Layer (`contracts.py`, `vault.py`, `trust.py`, `server_limits.py`)**: AES-256-GCM + scrypt secret vault, Ed25519 package signatures, anti-ZIP-Slip verification, CSRF/DNS-rebinding guards, and token-bucket rate limiting.
