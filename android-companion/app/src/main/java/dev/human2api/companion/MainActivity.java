package dev.human2api.companion;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.widget.*;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;

/** Visible, opt-in control panel. Android permissions are always granted by the user. */
public final class MainActivity extends Activity {
    private EditText packageName;
    private TextView status;
    private byte[] exportData;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().addFlags(android.view.WindowManager.LayoutParams.FLAG_SECURE);
        LinearLayout panel = new LinearLayout(this);
        panel.setOrientation(LinearLayout.VERTICAL); panel.setPadding(28,40,28,24);
        ScrollView scroll = new ScrollView(this); scroll.addView(panel); setContentView(scroll);
        TextView title = new TextView(this); title.setText("Human2API Companion"); title.setTextSize(27); panel.addView(title);
        TextView notice = new TextView(this);
        notice.setText("For your own authorized apps. Recording captures control identities, NOT typed values. Password controls are excluded. Execution lasts five minutes, only in the selected app. Stop is always available in the notification. No cloud connection is made.");
        notice.setPadding(0,20,0,20); panel.addView(notice);
        packageName = new EditText(this); packageName.setHint("Target package, e.g. com.android.settings"); panel.addView(packageName);
        button(panel,"1. Enable accessibility manually",()->startActivity(new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)));
        button(panel,"2. Start recording",()->begin(true));
        button(panel,"2. Arm desktop execution",()->begin(false));
        button(panel,"STOP",()->{if(CompanionService.instance!=null)CompanionService.instance.stopSession();status.setText("Stopped. No actions are permitted.");});
        button(panel,"Export recorded workflow",()->{
            try {
                if(CompanionService.instance==null)throw new IllegalStateException("Enable the accessibility service first");
                CompanionService.instance.stopSession();
                exportData=CompanionService.instance.workflow().toString(2).getBytes(StandardCharsets.UTF_8);
                Intent save=new Intent(Intent.ACTION_CREATE_DOCUMENT).setType("application/json").addCategory(Intent.CATEGORY_OPENABLE).putExtra(Intent.EXTRA_TITLE,"android_recording.json");
                startActivityForResult(save,20);
            } catch(Exception e){status.setText(e.getMessage());}
        });
        status=new TextView(this);status.setTextIsSelectable(true);status.setPadding(0,20,0,0);panel.addView(status);
    }
    private void button(LinearLayout panel,String text,Runnable action){Button b=new Button(this);b.setText(text);b.setOnClickListener(v->action.run());panel.addView(b);}
    private void begin(boolean recording){
        if(Build.VERSION.SDK_INT>=33&&checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)!=PackageManager.PERMISSION_GRANTED){requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS},10);status.setText("Grant notification permission, then press the button again.");return;}
        try{
            if(CompanionService.instance==null)throw new IllegalStateException("Accessibility service is not enabled");
            String pkg=packageName.getText().toString().trim();
            String token=CompanionService.instance.begin(pkg,recording);
            status.setText((recording?"Recording":"Execution armed")+" for five minutes.\nDesktop bridge token (keep private):\n"+token+"\n\nadb forward tcp:8766 tcp:8766\nAfter copying the token, switch to your selected app.");
        }catch(Exception e){status.setText(e.getMessage());}
    }
    @Override protected void onActivityResult(int request,int result,Intent data){
        super.onActivityResult(request,result,data);
        if(request==20&&result==RESULT_OK&&data!=null&&data.getData()!=null&&exportData!=null){
            try(OutputStream stream=getContentResolver().openOutputStream(data.getData())){
                if(stream==null)throw new IllegalStateException("No export destination");stream.write(exportData);status.setText("Exported. Review the workflow and supply its input variables on the desktop.");
            }catch(Exception e){status.setText("Export failed: "+e.getClass().getSimpleName());}
            java.util.Arrays.fill(exportData,(byte)0);exportData=null;
        }
    }
}
