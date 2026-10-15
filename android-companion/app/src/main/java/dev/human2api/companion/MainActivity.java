package dev.human2api.companion;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.provider.Settings;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.view.View;

import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;

/** User-controlled session consent; displays a one-session pairing token. */
public class MainActivity extends Activity {
    @Override protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        ScrollView scroll = new ScrollView(this);
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        int dp = (int) (16 * getResources().getDisplayMetrics().density);
        layout.setPadding(dp, dp, dp, dp);
        scroll.addView(layout);

        TextView title = new TextView(this);
        title.setText("Human2API Android Companion\nLocal USB-only automation. You control access.");
        title.setTextSize(18);
        layout.addView(title);

        TextView demoTitle = new TextView(this);
        demoTitle.setText("Demo: type a note and press Save. No real account is affected.");
        layout.addView(demoTitle);

        EditText demoInput = new EditText(this);
        demoInput.setId(R.id.demo_input);
        demoInput.setSingleLine(true);
        demoInput.setHint("Demo note");
        layout.addView(demoInput);

        TextView demoResult = new TextView(this);
        demoResult.setId(R.id.demo_result);
        demoResult.setText("Not saved yet");

        Button demoSubmit = new Button(this);
        demoSubmit.setId(R.id.demo_submit);
        demoSubmit.setText("Save demo note");
        demoSubmit.setOnClickListener(v -> demoResult.setText("Saved: " + demoInput.getText()));
        layout.addView(demoSubmit);
        layout.addView(demoResult);

        Button enable = new Button(this);
        enable.setText("1. Enable Human2API Accessibility Service");
        enable.setOnClickListener(v -> startActivity(new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)));
        layout.addView(enable);

        EditText packageInput = new EditText(this);
        packageInput.setSingleLine(true);
        packageInput.setHint("Allowed package e.g. com.android.settings");
        layout.addView(packageInput);

        TextView pairing = new TextView(this);
        pairing.setText("Pairing code: unavailable until you grant consent");
        pairing.setTextIsSelectable(true);
        // Never expose the one-time token through the accessibility snapshot API.
        pairing.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        pairing.setTextSize(15);
        layout.addView(pairing);

        TextView status = new TextView(this);
        status.setText("Service requires user approval in Android accessibility settings.");
        layout.addView(status);

        Button start = new Button(this);
        start.setText("2. Start 5-minute session");
        start.setOnClickListener(v -> {
            CompanionService service = CompanionService.getInstance();
            String raw = packageInput.getText().toString().trim();
            if (service == null) {
                status.setText("Please enable the Accessibility Service first.");
                return;
            }
            Set<String> packages = new HashSet<>(Arrays.asList(raw.split(",")));
            String token = service.grantSessionConsent(packages, CompanionService.SESSION_TTL_MS);
            if (token.isEmpty()) {
                status.setText("Enter an Android package ID such as com.android.settings.");
                return;
            }
            pairing.setText("One-time pairing code (valid up to 5 min):\n" + token);
            status.setText("ACTIVE. Open the allowed app, connect USB and run h2a android run on Windows.\nDo not share this code.");
        });
        layout.addView(start);

        Button stop = new Button(this);
        stop.setText("STOP - revoke access immediately");
        stop.setOnClickListener(v -> {
            CompanionService service = CompanionService.getInstance();
            if (service != null) service.stopSessionImmediately();
            pairing.setText("Pairing code revoked");
            status.setText("Session stopped.");
        });
        layout.addView(stop);
        setContentView(scroll);
    }
}
