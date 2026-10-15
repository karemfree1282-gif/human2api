package dev.human2api.companion;

import android.accessibilityservice.AccessibilityService;
import android.os.Bundle;
import android.os.SystemClock;
import android.util.Base64;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Real Android AccessibilityService and localhost-only ADB bridge.
 * A new unpredictable pairing token is generated on every explicit in-app consent.
 * The network API cannot grant consent, expand the package allowlist or read passwords.
 */
public class CompanionService extends AccessibilityService {
    public static final int BRIDGE_PORT = 18765;
    public static final long SESSION_TTL_MS = 300_000L;
    private static final int MAX_HTTP_REQUEST_BYTES = 65536;
    private static final int MAX_NODES = 256;
    private static final int MAX_DEPTH = 14;

    private static volatile CompanionService instance;
    private final AtomicBoolean running = new AtomicBoolean(false);
    private final AtomicBoolean consentActive = new AtomicBoolean(false);
    private final Set<String> allowedPackages = Collections.synchronizedSet(new HashSet<>());
    private volatile long sessionExpiresAtElapsed;
    private volatile String pairingToken = "";
    private ServerSocket serverSocket;

    public static CompanionService getInstance() { return instance; }

    @Override
    protected void onServiceConnected() {
        super.onServiceConnected();
        instance = this;
        startLoopbackBridge();
    }

    /** Called ONLY by the in-app Start button, never through a network endpoint. */
    public synchronized String grantSessionConsent(Set<String> packages, long ttlMs) {
        stopSessionImmediately();
        if (packages == null || packages.isEmpty()) return "";
        for (String pkg : packages) {
            if (pkg != null && pkg.trim().matches("[a-zA-Z_][a-zA-Z0-9_]*(\\.[a-zA-Z_][a-zA-Z0-9_]*)+")) {
                allowedPackages.add(pkg.trim());
            }
        }
        if (allowedPackages.isEmpty()) return "";
        byte[] tokenBytes = new byte[24];
        new SecureRandom().nextBytes(tokenBytes);
        pairingToken = Base64.encodeToString(tokenBytes, Base64.NO_WRAP | Base64.URL_SAFE | Base64.NO_PADDING);
        sessionExpiresAtElapsed = SystemClock.elapsedRealtime() + Math.min(SESSION_TTL_MS, Math.max(1L, ttlMs));
        consentActive.set(true);
        return pairingToken;
    }

    public synchronized void stopSessionImmediately() {
        consentActive.set(false);
        sessionExpiresAtElapsed = 0;
        pairingToken = "";
        allowedPackages.clear();
    }

    private boolean isSessionActive() {
        if (!consentActive.get()) return false;
        if (SystemClock.elapsedRealtime() >= sessionExpiresAtElapsed) {
            stopSessionImmediately();
            return false;
        }
        return true;
    }

    public boolean isSessionValidForPackage(String pkg) {
        return isSessionActive() && pkg != null && allowedPackages.contains(pkg);
    }

    public static boolean isSafeToCaptureNode(AccessibilityNodeInfo node) {
        if (node == null || node.isPassword()) return false;
        CharSequence resId = node.getViewIdResourceName();
        if (resId != null) {
            String id = resId.toString().toLowerCase(java.util.Locale.ROOT);
            if (id.contains("password") || id.contains("passcode") || id.contains("pin") ||
                id.contains("otp") || id.contains("cvv")) return false;
        }
        return true;
    }

    private static String str(CharSequence seq) { return seq == null ? "" : seq.toString(); }

    private AccessibilityNodeInfo getApprovedRoot() {
        if (!isSessionActive()) throw new SecurityException("Consent session missing or expired");
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null || !isSessionValidForPackage(str(root.getPackageName()))) {
            throw new SecurityException("Active app is not in the on-device package allowlist");
        }
        return root;
    }

    private static AccessibilityNodeInfo findPath(AccessibilityNodeInfo root, String path) {
        if (!path.matches("0(\\.[0-9]{1,3}){0,14}")) return null;
        String[] parts = path.split("\\.");
        AccessibilityNodeInfo node = root;
        for (int i = 1; i < parts.length; i++) {
            int child = Integer.parseInt(parts[i]);
            if (node == null || child >= node.getChildCount()) return null;
            node = node.getChild(child);
        }
        return node;
    }

    private void appendNodes(AccessibilityNodeInfo node, String id, JSONArray nodes, int depth) throws JSONException {
        if (node == null || nodes.length() >= MAX_NODES || depth > MAX_DEPTH) return;
        if (!isSafeToCaptureNode(node)) return; // Never reveal sensitive nodes or descendants.
        String pkg = str(node.getPackageName());
        if (!isSessionValidForPackage(pkg)) return;
        if (node.isVisibleToUser()) {
            JSONObject item = new JSONObject();
            item.put("node_id", id);
            item.put("resource_id", str(node.getViewIdResourceName()));
            item.put("text", str(node.getText()).substring(0, Math.min(500, str(node.getText()).length())));
            item.put("content_desc", str(node.getContentDescription()));
            item.put("class_name", str(node.getClassName()));
            item.put("package_name", pkg);
            item.put("clickable", node.isClickable());
            item.put("editable", node.isEditable());
            item.put("scrollable", node.isScrollable());
            item.put("enabled", node.isEnabled());
            item.put("visible", true);
            item.put("is_password", false);
            nodes.put(item);
        }
        for (int i = 0; i < node.getChildCount() && nodes.length() < MAX_NODES; i++) {
            appendNodes(node.getChild(i), id + "." + i, nodes, depth + 1);
        }
    }

    private JSONObject snapshot() throws JSONException {
        AccessibilityNodeInfo root = getApprovedRoot();
        JSONArray nodes = new JSONArray();
        appendNodes(root, "0", nodes, 0);
        JSONObject result = new JSONObject();
        result.put("status", "ok");
        result.put("package_name", str(root.getPackageName()));
        result.put("nodes", nodes);
        return result;
    }

    private JSONObject performAction(JSONObject command) throws JSONException {
        AccessibilityNodeInfo root = getApprovedRoot();
        String action = command.optString("action", "");
        boolean ok;
        if ("back".equals(action) || "home".equals(action)) {
            ok = performGlobalAction("back".equals(action) ? GLOBAL_ACTION_BACK : GLOBAL_ACTION_HOME);
        } else {
            String id = command.optString("node_id", "");
            AccessibilityNodeInfo node = findPath(root, id);
            if (node == null || !isSafeToCaptureNode(node) || !node.isEnabled() || !node.isVisibleToUser()) {
                throw new SecurityException("Target is missing, hidden or sensitive");
            }
            if (!isSessionValidForPackage(str(node.getPackageName()))) {
                throw new SecurityException("Target app not approved by the user");
            }
            String expectedResourceId = command.optString("resource_id", "");
            if (!expectedResourceId.isEmpty() && !expectedResourceId.equals(str(node.getViewIdResourceName()))) {
                throw new SecurityException("Target resource changed since the snapshot");
            }
            String expectedClassName = command.optString("class_name", "");
            if (!expectedClassName.isEmpty() && !expectedClassName.equals(str(node.getClassName()))) {
                throw new SecurityException("Target class changed since the snapshot");
            }
            String expectedDescription = command.optString("content_desc", "");
            if (!expectedDescription.isEmpty() && !expectedDescription.equals(str(node.getContentDescription()))) {
                throw new SecurityException("Target description changed since the snapshot");
            }
            if (!isSessionActive()) throw new SecurityException("Session expired before action");
            switch (action) {
                case "click":
                    if (!node.isClickable()) throw new SecurityException("Element is not clickable");
                    ok = node.performAction(AccessibilityNodeInfo.ACTION_CLICK);
                    break;
                case "type":
                case "fill":
                case "type_text":
                    if (!node.isEditable()) throw new SecurityException("Element is not editable");
                    Bundle text = new Bundle();
                    text.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE,
                            command.optString("text", ""));
                    ok = node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, text);
                    break;
                case "scroll":
                case "scroll_forward":
                    if (!node.isScrollable()) throw new SecurityException("Element is not scrollable");
                    ok = node.performAction(AccessibilityNodeInfo.ACTION_SCROLL_FORWARD);
                    break;
                default:
                    throw new IllegalArgumentException("Unsupported Android action");
            }
        }
        JSONObject result = new JSONObject();
        result.put("status", ok ? "ok" : "failed");
        result.put("performed", ok);
        return result;
    }

    private static class BridgeResponse {
        final int status;
        final JSONObject payload;
        BridgeResponse(int status, JSONObject payload) { this.status = status; this.payload = payload; }
    }
    private static JSONObject obj(String key, Object value) throws JSONException {
        JSONObject data = new JSONObject();
        data.put(key, value);
        return data;
    }
    private boolean authenticated(String provided) {
        String required = pairingToken;
        return isSessionActive() && !required.isEmpty() && provided != null &&
                MessageDigest.isEqual(required.getBytes(StandardCharsets.UTF_8),
                        provided.getBytes(StandardCharsets.UTF_8));
    }

    private BridgeResponse handle(String method, String path, String token, String body) throws JSONException {
        if ("GET".equals(method) && "/health".equals(path)) {
            JSONObject info = obj("status", "ok");
            info.put("service", "human2api-android-companion");
            info.put("session_active", isSessionActive());
            return new BridgeResponse(200, info);
        }
        // An emergency stop requires no token. Anyone with local device access can safely STOP.
        if ("POST".equals(method) && "/stop".equals(path)) {
            stopSessionImmediately();
            return new BridgeResponse(200, obj("status", "stopped"));
        }
        if (!authenticated(token)) return new BridgeResponse(403, obj("error", "Pairing token invalid or consent expired"));
        if ("GET".equals(method) && "/nodes".equals(path)) return new BridgeResponse(200, snapshot());
        if ("POST".equals(method) && "/action".equals(path)) return new BridgeResponse(200, performAction(new JSONObject(body)));
        return new BridgeResponse(404, obj("error", "Unknown endpoint"));
    }

    private static byte[] readHttp(InputStream input) throws java.io.IOException {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        int state = 0, b;
        while ((b = input.read()) != -1) {
            if (output.size() >= MAX_HTTP_REQUEST_BYTES) throw new java.io.IOException("Request too large");
            output.write(b);
            if ((state == 0 && b == '\r') || (state == 2 && b == '\r')) state++;
            else if ((state == 1 || state == 3) && b == '\n') state++;
            else state = b == '\r' ? 1 : 0;
            if (state == 4) break;
        }
        if (state != 4) throw new java.io.IOException("Incomplete HTTP headers");
        return output.toByteArray();
    }

    private void handleConnection(Socket client) throws Exception {
        client.setSoTimeout(3000);
        InputStream input = client.getInputStream();
        String headers = new String(readHttp(input), StandardCharsets.US_ASCII);
        String[] lines = headers.split("\\r\\n");
        String[] first = lines[0].split(" ");
        if (first.length < 2) throw new java.io.IOException("Malformed request");
        String token = null;
        int size = 0;
        for (int i = 1; i < lines.length; i++) {
            int colon = lines[i].indexOf(':');
            if (colon == -1) continue;
            String key = lines[i].substring(0, colon).trim().toLowerCase(java.util.Locale.ROOT);
            String value = lines[i].substring(colon + 1).trim();
            if ("x-h2a-token".equals(key)) token = value;
            if ("content-length".equals(key)) {
                try { size = Integer.parseInt(value); }
                catch (NumberFormatException exc) { throw new java.io.IOException("Bad Content-Length"); }
            }
        }
        if (size < 0 || size > MAX_HTTP_REQUEST_BYTES) throw new java.io.IOException("Invalid body size");
        byte[] bodyBytes = new byte[size];
        int n = 0;
        while (n < size) {
            int read = input.read(bodyBytes, n, size - n);
            if (read < 0) throw new java.io.IOException("Truncated body");
            n += read;
        }
        BridgeResponse response;
        try {
            response = handle(first[0], first[1], token, new String(bodyBytes, StandardCharsets.UTF_8));
        } catch (SecurityException exc) {
            response = new BridgeResponse(403, obj("error", exc.getMessage()));
        } catch (IllegalArgumentException | JSONException exc) {
            response = new BridgeResponse(400, obj("error", "Invalid action request"));
        }
        byte[] outputBody = response.payload.toString().getBytes(StandardCharsets.UTF_8);
        String statusText = response.status == 200 ? "OK" : "Error";
        String reply = "HTTP/1.1 " + response.status + " " + statusText + "\r\n" +
                "Content-Type: application/json; charset=utf-8\r\n" +
                "Cache-Control: no-store\r\n" +
                "Content-Length: " + outputBody.length + "\r\nConnection: close\r\n\r\n";
        OutputStream out = client.getOutputStream();
        out.write(reply.getBytes(StandardCharsets.US_ASCII));
        out.write(outputBody);
        out.flush();
    }

    private void startLoopbackBridge() {
        if (running.getAndSet(true)) return;
        Thread bridge = new Thread(() -> {
            try (ServerSocket server = new ServerSocket(BRIDGE_PORT, 8, InetAddress.getByName("127.0.0.1"))) {
                serverSocket = server;
                while (running.get()) {
                    try (Socket client = server.accept()) {
                        handleConnection(client);
                    } catch (Exception ignored) {
                        // Each connection is isolated. Never log credentials or request bodies.
                    }
                }
            } catch (Exception ignored) {
                running.set(false);
            }
        }, "human2api-android-local-bridge");
        bridge.setDaemon(true);
        bridge.start();
    }

    @Override public void onAccessibilityEvent(AccessibilityEvent event) {
        // Live snapshots are strictly on request; there is no background event recorder.
    }
    @Override public void onInterrupt() { stopSessionImmediately(); }
    @Override public void onDestroy() {
        running.set(false);
        stopSessionImmediately();
        try { if (serverSocket != null) serverSocket.close(); } catch (Exception ignored) {}
        instance = null;
        super.onDestroy();
    }
}
