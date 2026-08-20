package com.suhas.research360engine;

import android.app.Notification;
import android.content.Intent;
import android.os.Build;
import android.service.notification.NotificationListenerService;
import android.service.notification.StatusBarNotification;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Locale;

/** Captures only meaningful Research360 stock-call messages and aggressively deduplicates callbacks. */
public final class ResearchNotificationListener extends NotificationListenerService {
    private static final long DEDUPE_MS=4L*60L*1000L;

    @Override public void onNotificationPosted(StatusBarNotification sbn){
        try{
            if(sbn==null||sbn.getNotification()==null)return;
            Notification n=sbn.getNotification();
            String title=cs(n.extras.getCharSequence(Notification.EXTRA_TITLE));
            String text=cs(n.extras.getCharSequence(Notification.EXTRA_TEXT));
            String big=cs(n.extras.getCharSequence(Notification.EXTRA_BIG_TEXT));
            String summary=cs(n.extras.getCharSequence(Notification.EXTRA_SUMMARY_TEXT));
            CharSequence[] arr=n.extras.getCharSequenceArray(Notification.EXTRA_TEXT_LINES);
            StringBuilder lines=new StringBuilder();if(arr!=null)for(CharSequence x:arr)lines.append(cs(x)).append('\n');
            String raw=(title+"\n"+text+"\n"+big+"\n"+summary+"\n"+lines).trim();
            if(raw.isEmpty())return;
            String pkg=sbn.getPackageName();String label="";try{label=String.valueOf(getPackageManager().getApplicationLabel(getPackageManager().getApplicationInfo(pkg,0)));}catch(Exception ignored){}
            if(!isResearch360PackageOrBrand(pkg,label,raw))return;
            if(!meaningfulStockMessage(raw))return;

            String norm=normalize(raw);String fp=sha256(norm);
            if(!AppState.markNotificationIfNew(this,fp,DEDUPE_MS))return;

            R360Parser.Parsed p=R360Parser.parse(title,!big.isEmpty()?big:text,raw);
            // A valid captured message must identify a stock and a call action. Generic app cards/marketing are ignored.
            if(!p.parsed||p.symbol.isEmpty()||!("BUY".equals(p.action)||"CLOSE".equals(p.action)))return;
            if("BUY".equals(p.action)&&p.entry<=0)return;
            long since=System.currentTimeMillis()-DEDUPE_MS;
            if(Db.get(this).hasRecentSignal(p.category,p.action,p.symbol,p.entry,since))return;

            if(AppState.capturePackage(this).isEmpty())AppState.setCapturePackage(this,pkg);
            long sid=Db.get(this).insertNotification(sbn.getPostTime(),pkg,label,title,!big.isEmpty()?big:text,raw,p);
            if("BUY".equals(p.action))Db.get(this).log("R360",String.format(Locale.US,"BUY %s • %s • entry ₹%.2f • signal #%d",p.symbol,pretty(p.category),p.entry,sid));
            else Db.get(this).log("R360","CLOSE/EXIT update • "+p.symbol+" • "+pretty(p.category));
            if(AppState.isArmed(this))startEngine();
        }catch(Exception ex){Db.get(this).log("ERROR","Notification parser: "+ex.getClass().getSimpleName());}
    }

    private boolean isResearch360PackageOrBrand(String pkg,String label,String raw){
        String learned=AppState.capturePackage(this);String x=(label+" "+raw).toLowerCase(Locale.ROOT);
        boolean brand=x.contains("research 360")||x.contains("research360")||x.contains("most intraday cash")||x.contains("most overnight")||x.contains("quant intraday");
        // Learned package narrows provenance but never bypasses content validation.
        return brand||(!learned.isEmpty()&&learned.equals(pkg)&&containsCategory(x));
    }
    private static boolean containsCategory(String x){return x.contains("most intraday cash")||x.contains("most overnight")||x.contains("quant intraday");}
    private static boolean meaningfulStockMessage(String raw){
        String x=raw.toLowerCase(Locale.ROOT);if(!containsCategory(x))return false;
        boolean action=x.contains("buy ")||x.contains("buy call")||x.contains("call closed")||x.contains("book profit")||x.contains("advisable to exit")||x.contains("sell call")||x.contains("-profit")||x.contains("-loss");
        boolean price=x.contains(" rs")||x.contains("rs.")||x.contains("₹")||x.contains("entry")||x.contains("reached");return action&&price;
    }
    private static String normalize(String s){return s.toLowerCase(Locale.ROOT).replaceAll("\\s+"," ").replaceAll("[^a-z0-9₹.&_+:/ -]","").trim();}
    private static String sha256(String s){try{byte[] h=MessageDigest.getInstance("SHA-256").digest(s.getBytes(StandardCharsets.UTF_8));StringBuilder b=new StringBuilder();for(int i=0;i<10;i++)b.append(String.format(Locale.US,"%02x",h[i]));return b.toString();}catch(Exception e){return Integer.toHexString(s.hashCode());}}
    private static String pretty(String s){return s==null?"":s.replace('_',' ');}
    private void startEngine(){Intent i=new Intent(this,EngineService.class);if(Build.VERSION.SDK_INT>=26)startForegroundService(i);else startService(i);}
    private static String cs(CharSequence s){return s==null?"":s.toString();}
}
