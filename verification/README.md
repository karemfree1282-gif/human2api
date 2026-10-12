# Verification evidence

`local-v0.4.0.json` records a real run of the complete release checker. It reports 163 passing tests and four URL end-to-end tests blocked by managed Chromium policy. Hardware, native/Android compilation, hosted CI and public deployment gates remain blocked; there is no production-ready claim.

Reproduce with `h2a complete --repair --native --android` after installing platform tools and arranging authorized device/hosting access. The implementation source digest prevents reusing receipts for different code. Mocked platform contracts and real Chromium DOM tests are identified separately in the test suite.

The GitHub billing lock is independently confirmed in issue #8. Never suppress tests or fabricate acceptance to change a blocked report to green.
