# Human2API Android Companion — real ADB / Accessibility integration

This is a **companion app**, not a full Python server running standalone on Android. The Human2API runtime runs on a Windows, macOS or Linux computer. It controls a **user-approved Android application** via a USB-debugging / ADB-forwarded connection to the phone's on-device Accessibility Service.

## Build the APK

1. Install Android Studio and its **Android SDK Platform 34** and **Android SDK Build Tools 34.x**. Install a Java 17 JDK.
2. Run `python scripts/build_android.py` (or double-click `build-android.bat` on Windows). If Gradle is not installed, the script downloads **official Gradle 8.7** once, verifying the SHA-256 checksum published by Gradle. This first-time download requires internet access. No fake APK will be generated.
3. Building creates `android-companion/app/build/outputs/apk/debug/app-debug.apk` and verifies the APK exists.
4. Install with `adb install -r android-companion/app/build/outputs/apk/debug/app-debug.apk`.

## Pair and run an Android workflow

1. On your Android device, enable **Developer options** and **USB debugging**; authorize your computer when asked. Then enable `Human2API Companion` in **Settings → Accessibility**. Accessibility authorization must be granted manually on the phone.
2. In the companion app, type the safe self-test package ID `dev.human2api.companion`; select **Start 5-minute session**. The app displays a new single-use pairing code, valid only for the current 5-minute window. Keep the Companion app visible with the demo input/button on screen.
3. On your PC, run:

   ```sh
   h2a android doctor
   h2a android run --workflow src/human2api/examples/android_settings.json
   ```

   The run command checks ADB, forwards local TCP port 18765 to the phone, asks you for the pairing code privately, and executes the approved workflow. Use `--allow-write` when a workflow changes text or clicks a non-idempotent control. **No cloud API or root is required.**
4. Press **STOP** in the companion app to revoke the pairing code immediately. The session also expires after at most 5 minutes.

## Security and limitations

- The on-device API binds to `127.0.0.1:18765`, refuses requests without a valid session pairing code, and enforces the app allowlist on **every** action. The only unauthenticated mutating endpoint is STOP (fail-closed).
- Password/PIN/OTP/CVV UI nodes are neither exposed nor controlled; no background screen recording is performed.
- ADB over USB is the preferred connection. Keep USB debugging off when not using the application.
- Android may restrict accessibility automation on some screens; input and UI hierarchy IDs vary across manufacturers, so example Settings selectors may need adjustment.
- A real APK **cannot** be built or tested without an Android SDK + Gradle; a connected Android device or emulator is required for real-device end-to-end verification.

The built-in demo edits only an on-screen note in the Companion. To control Android Settings or another app, enter that app package in the on-phone allowlist and build/use a matching workflow.
