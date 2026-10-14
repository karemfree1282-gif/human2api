package dev.human2api.companion;

import android.accessibilityservice.AccessibilityService;
import android.os.Bundle;
import android.os.SystemClock;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.Collections;
import java.util.HashSet;
import java.util.Set;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Consent-scoped Android AccessibilityService for Human2API.
 * Enforces:
 * - Loopback-only HTTP bridge (127.0.0.1:18765) for ADB forwarding
 * - Explicit 5-minute user consent session TTL
 * - Package allowlist enforcement (refuses actions on unauthorized apps)
 * - Password & sensitive field exclusion (never reads or records node.isPassword())
 * - Full Arabic and Unicode text input via ACTION_SET_TEXT
 * - Immediate cooperative and broadcast STOP switch
 */
public class CompanionService extends AccessibilityService {
    public static final int BRIDGE_PORT = 18765;
    public static final long SESSION_TTL_MS = 300_000L; // 5 minutes

    private static volatile CompanionService instance;
    private final AtomicBoolean running = new AtomicBoolean(false);
    private final AtomicBoolean consentActive = new AtomicBoolean(false);
    private volatile long sessionExpiresAtElapsed = 0L;
    private final Set<String> allowedPackages = Collections.synchronizedSet(new HashSet<>());
    private ServerSocket serverSocket;

    public static CompanionService getInstance() {
        return instance;
    }

    @Override
    protected void onServiceConnected() {
        super.onServiceConnected();
        instance = this;
        startLoopbackBridge();
    }

    public synchronized void grantSessionConsent(Set<String> packages, long ttlMs) {
        allowedPackages.clear();
        if (packages != null) {
            allowedPackages.addAll(packages);
        }
        sessionExpiresAtElapsed = SystemClock.elapsedRealtime() + (ttlMs > 0 ? ttlMs : SESSION_TTL_MS);
        consentActive.set(true);
    }

    public synchronized void stopSessionImmediately() {
        consentActive.set(false);
        sessionExpiresAtElapsed = 0L;
        allowedPackages.clear();
    }

    public boolean isSessionValidForPackage(String packageName) {
        if (!consentActive.get()) {
            return false;
        }
        if (SystemClock.elapsedRealtime() > sessionExpiresAtElapsed) {
            stopSessionImmediately();
            return false;
        }
        if (packageName == null || packageName.isEmpty()) {
            return false;
        }
        return allowedPackages.contains(packageName);
    }

    public static boolean isSafeToCaptureNode(AccessibilityNodeInfo node) {
        if (node == null) {
            return false;
        }
        if (node.isPassword()) {
            return false;
        }
        CharSequence viewId = node.getViewIdResourceName();
        if (viewId != null) {
            String lower = viewId.toString().toLowerCase();
            if (lower.contains("password") || lower.contains("pin") || lower.contains("otp") || lower.contains("cvv")) {
                return false;
            }
        }
        return true;
    }

    public boolean performActionOnNode(AccessibilityNodeInfo root, String targetResourceId, String action, String unicodeText) {
        if (root == null || targetResourceId == null) {
            return false;
        }
        CharSequence pkg = root.getPackageName();
        if (pkg == null || !isSessionValidForPackage(pkg.toString())) {
            throw new SecurityException("Unauthorized package or expired session: " + pkg);
        }
        java.util.List<AccessibilityNodeInfo> matches = root.findAccessibilityNodeInfosByViewId(targetResourceId);
        if (matches == null || matches.size() != 1) {
            return false;
        }
        AccessibilityNodeInfo target = matches.get(0);
        if (!target.isEnabled() || !target.isVisibleToUser()) {
            return false;
        }
        if ("click".equals(action)) {
            return target.performAction(AccessibilityNodeInfo.ACTION_CLICK);
        } else if ("type_text".equals(action) || "type".equals(action)) {
            Bundle args = new Bundle();
            args.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, unicodeText != null ? unicodeText : "");
            return target.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args);
        } else if ("scroll_forward".equals(action)) {
            return target.performAction(AccessibilityNodeInfo.ACTION_SCROLL_FORWARD);
        }
        return false;
    }

    private void startLoopbackBridge() {
        if (running.getAndSet(true)) {
            return;
        }
        Thread bridgeThread = new Thread(() -> {
            try {
                serverSocket = new ServerSocket(BRIDGE_PORT, 8, InetAddress.getByName("127.0.0.1"));
                while (running.get()) {
                    try (Socket client = serverSocket.accept()) {
                        client.setSoTimeout(5000);
                        BufferedReader reader = new BufferedReader(new InputStreamReader(client.getInputStream(), StandardCharsets.UTF_8));
                        String requestLine = reader.readLine();
                        String responseJson = "{\"status\":\"ok\",\"service\":\"h2a-loopback-bridge\",\"consentActive\":" + consentActive.get() + "}";
                        if (requestLine != null && requestLine.contains("/stop")) {
                            stopSessionImmediately();
                            responseJson = "{\"status\":\"stopped\"}";
                        }
                        byte[] bodyBytes = responseJson.getBytes(StandardCharsets.UTF_8);
                        OutputStream out = client.getOutputStream();
                        String headers = "HTTP/1.1 200 OK\r\nContent-Type: application/json; charset=utf-8\r\nContent-Length: " + bodyBytes.length + "\r\nConnection: close\r\n\r\n";
                        out.write(headers.getBytes(StandardCharsets.UTF_8));
                        out.write(bodyBytes);
                        out.flush();
                    } catch (Exception ignored) {
                    }
                }
            } catch (Exception ignored) {
            }
        }, "h2a-loopback-bridge");
        bridgeThread.setDaemon(true);
        bridgeThread.start();
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
        if (event == null || !consentActive.get()) {
            return;
        }
        CharSequence pkg = event.getPackageName();
        if (pkg == null || !isSessionValidForPackage(pkg.toString())) {
            return;
        }
        if (event.isPassword()) {
            // Never record password events
            return;
        }
    }

    @Override
    public void onInterrupt() {
        stopSessionImmediately();
    }

    @Override
    public void onDestroy() {
        running.set(false);
        stopSessionImmediately();
        try {
            if (serverSocket != null) {
                serverSocket.close();
            }
        } catch (Exception ignored) {
        }
        instance = null;
        super.onDestroy();
    }
}
