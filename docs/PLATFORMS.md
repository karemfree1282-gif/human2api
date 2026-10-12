# Platform setup and boundaries

## Browser

Install Python 3.10+ and `python -m playwright install chromium`. The core creates a fresh browser context; it does not read your everyday browser profile. A recorded task uses runtime input variables rather than retaining typed values. Inspect recorded hosts, selectors and operations before running it.

For nested frames, use `frames: ["iframe#outer", "iframe#inner"]`. The legacy single `frame` string remains supported. The two fields are mutually exclusive. Recording stops without saving a partial task when an iframe cannot be addressed by unique stable identifiers. The maximum is ten frame levels and 250 actions. Duplicate control names in different tabs/frames/locations receive separate variables.

`networkPolicy: "strict"` gates Playwright-routed HTTP(S) resources and blocks WebSockets; it is **not** a complete network firewall. Browser engine internals, DNS, WebRTC and the operating system require separate network isolation for hostile content. `deploy/Dockerfile.browser` is an optional unprivileged container build; use read-only input mounts, a writable output directory, capability drops and a deliberately restricted network. Never mount the Docker socket or your personal browser profile.

## Windows

Install `human2api[desktop,accessibility,studio]`. UI Automation must have permission to inspect the target's privilege level. Human2API does not elevate itself or bypass protected processes. `ui_fill` uses the accessible value API for Unicode, not the clipboard. Password controls are rejected. The optional WebView2 runtime must be present for the native Studio window.

`h2a record-desktop --smart --name task` records unique UIA controls when available. A click on an editable field creates a secret runtime placeholder; it does not capture the demonstration text. Finish with F12. Put the pointer in the upper-left corner to invoke the PyAutoGUI fallback's failsafe.

## macOS

Install the same extras; PyObjC ApplicationServices and Cocoa are selected only on macOS. Grant the particular terminal/application Accessibility permission in System Settings. AXIdentifier or a unique accessible name is used; AXValue supplies Unicode text. Secure text controls and ambiguous windows fail closed.

The build script produces a native `.app` distribution and DMG on macOS. This does not imply Developer ID signing or notarization. Do not disable Gatekeeper globally to run a build.

## Linux

A logged-in desktop session with AT-SPI is required. Install your distribution's `python3-pyatspi`/PyGObject packages. Use a virtual environment made with `--system-site-packages` when those bindings are provided by the system Python. The system Python and environment must have compatible versions.

For example, on a compatible Debian/Ubuntu desktop, install `python3-pyatspi`, `python3-venv`, then create the environment using `/usr/bin/python3 -m venv --system-site-packages .venv`. Qt Studio additionally needs `PySide6` and its system shared libraries. `H2A_WEBVIEW_GUI` selects another installed pywebview backend explicitly.

Native selectors use AT-SPI accessible IDs/names and editable-text/action interfaces. Pointer replay may be restricted on Wayland. The tool reports that restriction; it does not disable display security. Pixel coordinates are not promoted as robust selectors.

## Android

Install the [companion](../android-companion/README.md) on your authorized test phone, grant Accessibility and notification permission yourself, select the exact target package, and explicitly start recording or arm execution. USB debugging and `adb forward tcp:8766 tcp:8766` are required for the desktop bridge. Supply the short-lived token via `H2A_ANDROID_BRIDGE_TOKEN` in your shell, never a committed file.

The legacy ADB teaching wizard remains available. Plain ADB text supports a restricted ASCII alphabet. Unicode `set_text`/`input_text`, stable control clicks and native scrolling use the armed companion. Device protection/DRM/secure password controls are not bypassed. UIAutomator temporary dumps are removed after bounded reads.

## Verification

Tests using simulated AX/UIA/AT-SPI/ADB objects establish Python contract behavior only. They do not establish driver compatibility or a successful physical device session. Record separate operator acceptance on every intended OS/device family using `scripts/acceptance_probe.py` and synthetic data. See [acceptance](ACCEPTANCE.md).
