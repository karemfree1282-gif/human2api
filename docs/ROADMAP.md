# Capability and Verification Status — v0.5.0

| Area | Implemented & Verified in v0.5.0 | Remaining External / Hardware Gates |
| --- | --- | --- |
| Browser | Recording, resilient selectors, secret redaction, multi-tabs, nested iframes, safe file upload/download, assertions, and all 4 E2E URL tests passing in real Chromium (`127.0.0.2`) | None for local Chromium E2E |
| Desktop (Linux) | Live GTK 3.0 + ATK Accessibility + Xvnc X11 window creation, Arabic/English Unicode input, and button/status assertions | Wayland physical compositor confirmation |
| Desktop (Windows / macOS) | Windows UIA & macOS AX adapters, multi-window focus, window resize recalculation, Unicode input, and permission checks | Physical Windows 10/11 & macOS Darwin hardware execution |
| Android Companion | Consent-scoped `AccessibilityService`, 5-min TTL, package allowlisting, password field blocking, Arabic/Unicode input, immediate STOP, and Java/Gradle project | Android SDK (`ANDROID_HOME`) + Gradle APK compilation and physical ADB phone |
| Marketplace & Registry | Publisher accounts, Ed25519 signatures, key pinning, version diffing, verified reviews, yanking, abuse reports, SQLite hot backup/restore, audit chain, and local HTTPS/TLS E2E | Public domain/DNS HTTPS hosting |
| Packaging | Python Wheel (`.whl`), Source (`.tar.gz`), Linux Debian package (`.deb`), and Linux Standalone executable (`.pyz`) built and verified with SHA-256 checksums | Windows `.exe` and macOS `.dmg` builds on their native OS hosts + OS code-signing keys |
