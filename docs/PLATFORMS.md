# Platform Support & Accessibility Matrix

| Platform | Engine | Accessibility API | Supported Controls | Known OS Boundaries |
| --- | --- | --- | --- | --- |
| Browser | `browser` / `web` | DOM + ARIA (`Chromium` / `Playwright`) | Buttons, inputs, selects, multi-tabs, nested iframes, file uploads/downloads | Cross-origin frames without CORS require `framePath` selector |
| Windows | `windows-uia` | Microsoft UI Automation (UIA) | `AutomationId`, `Name`, `Role`, multi-windows, Arabic/English Unicode | Elevated UAC admin windows require matching integrity level |
| macOS | `macos-ax` | Apple AX Accessibility (`AXUIElement`) | `AXRole`, `AXTitle`, `AXIdentifier`, windows, fields, buttons | Requires user approval in `System Settings > Privacy & Security > Accessibility` |
| Linux | `linux-atspi` | AT-SPI2 / GTK3+ATK (`X11` & `Wayland`) | GTK3/Qt widgets, `automation_id`, `role`, `name`, Unicode text | Wayland blocks global coordinate injection; AT-SPI/ATK tree actions work natively |
| Android | `android-companion` | Android `AccessibilityService` + ADB | `resourceId`, `contentDesc`, `ACTION_CLICK`, `ACTION_SET_TEXT` (Arabic/Unicode) | 5-minute user consent session TTL; custom OpenGL/Canvas games without Accessibility nodes are not automatable |
