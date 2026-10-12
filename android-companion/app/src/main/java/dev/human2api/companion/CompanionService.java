package dev.human2api.companion;

import android.accessibilityservice.AccessibilityService;
import android.app.*;
import android.content.Intent;
import android.os.*;
import android.view.accessibility.*;
import org.json.*;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.security.*;
import java.util.*;
import java.util.concurrent.*;

/** Explicit five-minute sessions, package-scoped actions, no key/text capture. */
public final class CompanionService extends AccessibilityService {
    public static volatile CompanionService instance;
    private final Handler main=new Handler(Looper.getMainLooper());
    private volatile boolean recording=false, armed=false;
    private volatile long expires=0;
    private volatile String token="", target="", recordedTarget="";
    private ServerSocket server;
    private JSONArray steps=new JSONArray();
    private JSONObject inputs=new JSONObject();
    private final Map<String,String> variables=new HashMap<>();
    private final LinkedHashMap<String,JSONObject> replies=new LinkedHashMap<>();
    private String lastField="";

    @Override protected void onServiceConnected(){
        instance=this;
        NotificationManager nm=getSystemService(NotificationManager.class);
        nm.createNotificationChannel(new NotificationChannel("h2a","Human2API explicit sessions",NotificationManager.IMPORTANCE_LOW));
        new Thread(this::listen,"h2a-loopback-bridge").start();
    }
    public synchronized String begin(String pkg,boolean capture){
        if(!pkg.matches("[A-Za-z][A-Za-z0-9_]*(\\.[A-Za-z0-9_]+)+")||pkg.equals(getPackageName()))throw new IllegalArgumentException("Enter the exact package of an authorized target app");
        if(!getSystemService(NotificationManager.class).areNotificationsEnabled()||getSystemService(NotificationManager.class).getNotificationChannel("h2a").getImportance()==NotificationManager.IMPORTANCE_NONE)throw new IllegalStateException("Enable the recording notification before starting");
        if(Build.VERSION.SDK_INT>=33&&checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS)!=android.content.pm.PackageManager.PERMISSION_GRANTED)throw new IllegalStateException("Grant notification permission before starting");
        byte[] random=new byte[32];new SecureRandom().nextBytes(random);StringBuilder s=new StringBuilder();for(byte b:random)s.append(String.format(Locale.ROOT,"%02x",b));
        token=s.toString();target=pkg;recording=capture;armed=!capture;expires=SystemClock.elapsedRealtime()+300000;
        replies.clear();
        if(capture){recordedTarget=pkg;steps=new JSONArray();inputs=new JSONObject();variables.clear();lastField="";}
        PendingIntent stop=PendingIntent.getBroadcast(this,0,new Intent(this,StopReceiver.class),PendingIntent.FLAG_IMMUTABLE|PendingIntent.FLAG_UPDATE_CURRENT);
        PendingIntent open=PendingIntent.getActivity(this,0,new Intent(this,MainActivity.class),PendingIntent.FLAG_IMMUTABLE|PendingIntent.FLAG_UPDATE_CURRENT);
        Notification notification=new Notification.Builder(this,"h2a").setSmallIcon(android.R.drawable.ic_menu_view)
          .setContentTitle(capture?"Human2API: RECORDING":"Human2API: execution ARMED")
          .setContentText("Only "+pkg+". Auto-stop after five minutes.").setOngoing(true).setContentIntent(open)
          .addAction(new Notification.Action.Builder(null,"STOP",stop).build()).build();
        getSystemService(NotificationManager.class).notify(42,notification);
        final long until=expires;main.postDelayed(()->{if(expires==until)stopSession();},300000);
        return token;
    }
    public synchronized void stopSession(){recording=false;armed=false;token="";replies.clear();getSystemService(NotificationManager.class).cancel(42);}
    private boolean active(){NotificationManager nm=getSystemService(NotificationManager.class);if(SystemClock.elapsedRealtime()>=expires||!nm.areNotificationsEnabled()||nm.getNotificationChannel("h2a").getImportance()==NotificationManager.IMPORTANCE_NONE){stopSession();return false;}return true;}
    @Override public void onInterrupt(){stopSession();}
    @Override public void onDestroy(){stopSession();instance=null;try{if(server!=null)server.close();}catch(IOException ignored){}super.onDestroy();}

    @Override public synchronized void onAccessibilityEvent(AccessibilityEvent event){
        if(!recording||!active()||steps.length()>=250||event.getPackageName()==null||!target.contentEquals(event.getPackageName()))return;
        AccessibilityNodeInfo n=event.getSource();
        if(n==null||n.isPassword()||!n.isVisibleToUser())return;
        String id=n.getViewIdResourceName();
        // No event.getText() / node.getText(): private values never enter the recorder.
        String selector=id;String by="resource-id";
        if(selector==null||selector.isEmpty()){CharSequence label=n.getContentDescription();selector=label==null?"":label.toString();by="content-desc";}
        if(selector.isEmpty()||selector.length()>300)return;
        try{
            if(event.getEventType()==AccessibilityEvent.TYPE_VIEW_CLICKED){
                steps.put(new JSONObject().put("action","tap_text").put("selector",selector).put("by",by));lastField="";
            }else if(event.getEventType()==AccessibilityEvent.TYPE_VIEW_SCROLLED&&n.isScrollable()&&Build.VERSION.SDK_INT>=28){
                int delta=event.getScrollDeltaY();
                if(delta!=0){steps.put(new JSONObject().put("action","scroll_node").put("selector",selector).put("by",by).put("direction",delta>0?"forward":"backward"));lastField="";}
            }else if(event.getEventType()==AccessibilityEvent.TYPE_VIEW_TEXT_CHANGED&&n.isEditable()){
                String identity=by+":"+selector;
                if(identity.equals(lastField))return;
                String variable=variables.get(identity);
                if(variable==null){variable="input_"+(variables.size()+1);variables.put(identity,variable);inputs.put(variable,new JSONObject().put("type","string").put("required",true).put("secret",true));}
                steps.put(new JSONObject().put("action","set_text").put("selector",selector).put("by",by).put("value","{{"+variable+"}}"));lastField=identity;
            }
        }catch(JSONException ignored){}
    }
    public synchronized JSONObject workflow() throws JSONException {
        if(steps.length()==0)throw new IllegalStateException("No supported actions recorded in the selected app");
        return new JSONObject().put("schemaVersion",1).put("name","android_recording").put("description","User-authorized Android accessibility recording")
          .put("target","android").put("appPackage",recordedTarget).put("permissions","write").put("inputs",new JSONObject(inputs.toString())).put("steps",new JSONArray(steps.toString()));
    }
    private synchronized JSONObject dispatch(String path,JSONObject body,String requestToken) throws Exception {
        if(!MessageDigest.isEqual(token.getBytes(StandardCharsets.UTF_8),requestToken.getBytes(StandardCharsets.UTF_8)))throw new SecurityException("Session was rotated");
        if(path.equals("/recording")){if(!recording||!active())throw new SecurityException("No active recording session");return workflow();}
        if(!path.equals("/action"))throw new IllegalArgumentException("Unknown route");
        if(!armed||!active())throw new SecurityException("Arm execution explicitly on the phone first");
        if(!target.equals(body.optString("package")))throw new SecurityException("Target package differs from the phone's approved scope");
        String requestId=body.optString("requestId");
        if(!requestId.matches("[a-f0-9]{24,64}"))throw new IllegalArgumentException("A unique requestId is required");
        if(replies.containsKey(requestId))return replies.get(requestId);
        AccessibilityNodeInfo root=getRootInActiveWindow();
        if(root==null||root.getPackageName()==null||!target.contentEquals(root.getPackageName()))throw new SecurityException("The approved app is not the active window");
        String action=body.optString("action");boolean ok=false;
        if(action.equals("back")){ok=performGlobalAction(GLOBAL_ACTION_BACK);}
        else {
            String selector=body.optString("selector"),by=body.optString("by","resource-id");
            AccessibilityNodeInfo chosen=null;
            if(selector.isEmpty()&&action.equals("set_text")){chosen=root.findFocus(AccessibilityNodeInfo.FOCUS_INPUT);}
            else {
                ArrayDeque<AccessibilityNodeInfo> queue=new ArrayDeque<>();queue.add(root);int seen=0,matches=0;
                while(!queue.isEmpty()){
                    AccessibilityNodeInfo n=queue.remove();if(++seen>3000)throw new IllegalStateException("UI tree too large");
                    String label=by.equals("resource-id")?n.getViewIdResourceName():by.equals("content-desc")?(n.getContentDescription()==null?null:n.getContentDescription().toString()):null;
                    if(!n.isPassword()&&n.isVisibleToUser()&&selector.equals(label)){chosen=n;matches++;}
                    for(int i=0;i<n.getChildCount();i++){AccessibilityNodeInfo child=n.getChild(i);if(child!=null)queue.add(child);}
                }
                if(matches!=1)throw new IllegalStateException("Selector must identify exactly one control");
            }
            if(chosen==null||chosen.isPassword()||!chosen.isEnabled()||!chosen.isVisibleToUser())throw new SecurityException("Unavailable or protected control");
            if(action.equals("click")){ok=chosen.performAction(AccessibilityNodeInfo.ACTION_CLICK);}
            else if(action.equals("set_text")){
                if(!chosen.isEditable())throw new IllegalStateException("Control is not editable");
                String value=body.getString("value");if(value.length()>10000)throw new IllegalArgumentException("Text too long");
                Bundle args=new Bundle();args.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE,value);ok=chosen.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT,args);
            }else if(action.equals("scroll_forward")||action.equals("scroll_backward")){
                if(!chosen.isScrollable())throw new IllegalStateException("Control is not scrollable");
                ok=chosen.performAction(action.equals("scroll_forward")?AccessibilityNodeInfo.ACTION_SCROLL_FORWARD:AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD);
            }else throw new IllegalArgumentException("Unsupported action");
        }
        JSONObject response=new JSONObject().put("ok",ok);
        replies.put(requestId,response);if(replies.size()>500)replies.remove(replies.keySet().iterator().next());
        if(!ok)throw new IllegalStateException("Android rejected the action; do not retry blindly");
        return response;
    }
    private void listen(){
        try{server=new ServerSocket();server.bind(new InetSocketAddress(InetAddress.getByName("127.0.0.1"),8766));
            while(!server.isClosed()){try(Socket client=server.accept()){client.setSoTimeout(10000);handle(client);}catch(Exception ignored){}}
        }catch(IOException ignored){stopSession();}
    }
    private static String line(InputStream in) throws IOException {
        ByteArrayOutputStream out=new ByteArrayOutputStream();int b;
        while((b=in.read())!=-1){if(b==10)break;if(out.size()>=4096)throw new IOException("Header too long");if(b!=13)out.write(b);}
        return out.toString(StandardCharsets.US_ASCII.name());
    }
    private void handle(Socket socket) throws Exception {
        int code=200;JSONObject response;
        try{
            InputStream in=socket.getInputStream();String first=line(in);String[] request=first.split(" ");
            if(request.length!=3||(!request[0].equals("POST")&&!request[0].equals("GET")))throw new IllegalArgumentException("Invalid method");
            Map<String,String> headers=new HashMap<>();int count=0;String row;
            while(!(row=line(in)).isEmpty()){
                if(++count>30)throw new IllegalArgumentException("Too many headers");int colon=row.indexOf(':');if(colon<1)throw new IllegalArgumentException("Malformed header");
                String name=row.substring(0,colon).toLowerCase(Locale.ROOT);if(headers.put(name,row.substring(colon+1).trim())!=null)throw new IllegalArgumentException("Duplicate header");
            }
            String supplied=headers.getOrDefault("x-h2a-token","");
            if(token.isEmpty()||!MessageDigest.isEqual(token.getBytes(StandardCharsets.UTF_8),supplied.getBytes(StandardCharsets.UTF_8)))throw new SecurityException("Invalid bridge token");
            if(headers.containsKey("origin")||headers.containsKey("transfer-encoding"))throw new SecurityException("Browser and chunked requests are not accepted");
            if(request[1].equals("/action")&&!request[0].equals("POST"))throw new IllegalArgumentException("Actions require POST");
            int length=Integer.parseInt(headers.getOrDefault("content-length","0"));if(length<0||length>65536)throw new IllegalArgumentException("Body too large");
            byte[] raw=new byte[length];int received=0;while(received<length){int n=in.read(raw,received,length-received);if(n<0)throw new EOFException();received+=n;}
            JSONObject body=length==0?new JSONObject():new JSONObject(new String(raw,StandardCharsets.UTF_8));
            FutureTask<JSONObject> task=new FutureTask<>(()->dispatch(request[1],body,supplied));main.post(task);
            try{response=task.get(10,TimeUnit.SECONDS);}catch(TimeoutException e){task.cancel(false);throw e;}
        }catch(Exception e){code=400;response=new JSONObject().put("ok",false).put("error","Request rejected or action failed. Verify the armed session, package and selector; do not blindly retry.");}
        byte[] payload=response.toString().getBytes(StandardCharsets.UTF_8);
        OutputStream out=socket.getOutputStream();out.write(("HTTP/1.1 "+code+(code==200?" OK":" Bad Request")+"\r\nContent-Type: application/json\r\nCache-Control: no-store\r\nConnection: close\r\nContent-Length: "+payload.length+"\r\n\r\n").getBytes(StandardCharsets.US_ASCII));out.write(payload);out.flush();
    }
}
