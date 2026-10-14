package dev.human2api.companion;

import android.app.Activity;
import android.os.Bundle;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;

/**
 * Main consent and control activity for Human2API Android Companion.
 * Allows user to explicitly specify allowed target package(s), start a 5-minute session, or stop immediately.
 */
public class MainActivity extends Activity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        int pad = 32;
        layout.setPadding(pad, pad, pad, pad);

        TextView title = new TextView(this);
        title.setText("Human2API Android Companion (v0.5.0)");
        layout.addView(title);

        EditText packageInput = new EditText(this);
        packageInput.setHint("Allowed package (e.g. com.android.settings)");
        layout.addView(packageInput);

        TextView statusView = new TextView(this);
        statusView.setText("Session: Inactive");
        layout.addView(statusView);

        Button startBtn = new Button(this);
        startBtn.setText("Grant 5-Min Consent & Start Session");
        startBtn.setOnClickListener(v -> {
            CompanionService svc = CompanionService.getInstance();
            String raw = packageInput.getText().toString().trim();
            if (svc != null && !raw.isEmpty()) {
                Set<String> pkgs = new HashSet<>(Arrays.asList(raw.split("\\s*,\\s*")));
                svc.grantSessionConsent(pkgs, CompanionService.SESSION_TTL_MS);
                statusView.setText("Session: Active for " + pkgs);
            } else {
                statusView.setText("Enable AccessibilityService and enter an allowed package first.");
            }
        });
        layout.addView(startBtn);

        Button stopBtn = new Button(this);
        stopBtn.setText("STOP Immediately");
        stopBtn.setOnClickListener(v -> {
            CompanionService svc = CompanionService.getInstance();
            if (svc != null) {
                svc.stopSessionImmediately();
            }
            statusView.setText("Session: Stopped Immediately");
        });
        layout.addView(stopBtn);

        setContentView(layout);
    }
}
