package dev.human2api.companion;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/**
 * BroadcastReceiver allowing one-tap immediate cancellation of any active recording or execution session.
 */
public class StopReceiver extends BroadcastReceiver {
    public static final String ACTION_STOP_SESSION = "dev.human2api.companion.ACTION_STOP_SESSION";

    @Override
    public void onReceive(Context context, Intent intent) {
        if (intent != null && ACTION_STOP_SESSION.equals(intent.getAction())) {
            CompanionService svc = CompanionService.getInstance();
            if (svc != null) {
                svc.stopSessionImmediately();
            }
        }
    }
}
