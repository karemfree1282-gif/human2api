# Human2API Android companion

Consent-based recording and package-scoped execution for an **owned or explicitly authorized test app**. There is no background cloud relay, root requirement or silent permission grant.

## Build

Install JDK 17+, Gradle **8.11.1** and Android SDK platform **35** through your normal licensed SDK installation. The project uses Android Gradle Plugin **8.9.2**. From the repository root:

```bash
python scripts/build_android.py --output dist/android
```

This compiles, runs Android lint/unit-test tasks, and copies the **debug-signed test APK** plus its SHA-256 receipt. A debug build is not a store release. Production signing keys must stay outside Git. The Android build workflow runs the same command. No APK is claimed to have been built merely because the source exists.

## Record

1. Install the debug APK on the test phone. Open Human2API Companion.
2. Enable its Accessibility service yourself in Android settings and allow its visible notification.
3. Enter the target app's exact package, press **Start recording**, and switch to that app.
4. Perform clicks, edit fields, and scroll. Typed values are never read by the recorder; editable controls produce required secret variables. Resource IDs are preferred, with content descriptions as a fallback.
5. Stop from the notification or control panel and export the JSON through the Android document picker. Review it in the desktop visual editor before execution.

Only supported events with stable selectors are recorded. Apps that omit accessibility metadata need manual reviewed steps. API 26-27 do not provide the scroll-delta capture used on API 28+. System back gestures, arbitrary swipes and opaque canvas interactions are not inferred from unrelated events. The 250-action limit and five-minute session boundary are explicit.

## Execute Unicode and native selectors

```bash
adb forward tcp:8766 tcp:8766
```

Press **Arm desktop execution** for the target package. Set the displayed token in the desktop process environment as `H2A_ANDROID_BRIDGE_TOKEN`; do not send it to others. Switch to the approved app. Run the reviewed workflow with `--approve`.

The bridge binds **127.0.0.1:8766 on the phone**, verifies a constant-time token and the active package, and rechecks unique visible enabled non-password controls before acting. Tokens rotate on arming and are revoked on Stop/expiry. Notifications must remain enabled. The token display uses `FLAG_SECURE` to reduce accidental screen capture.

Bridge operations: scoped click, Unicode set-text, scroll-forward/backward, and back. Request IDs deduplicate repeated delivery within an armed session, but the desktop client never blindly retries mutations. Timeouts are ambiguous outcomes: inspect the phone before repeating a write. ADB itself is privileged and must be disabled/revoked when not needed.

## Testing status

Source-level privacy tests and Python bridge tests are not Android device acceptance. Build/lint and test this APK on actual target Android versions before general release. Do not advertise the service as an Android Accessibility Tool for disabled users unless its actual purpose and applicable policies justify that classification; the manifest does not make that claim.
