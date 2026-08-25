package com.suhas.multyfifastbuy;

import android.app.Notification;
import android.service.notification.NotificationListenerService;
import android.service.notification.StatusBarNotification;

import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class MultyfiNotificationListener extends NotificationListenerService {
    private static final Pattern STOCK = Pattern.compile("(?i)Stock\\s*Name\\s*:\\s*([^\\n\\r]+)");
    private static final Pattern TARGET = Pattern.compile("(?i)Target\\s*:\\s*([0-9]+(?:\\.[0-9]+)?)");
    private static final Pattern RANGE = Pattern.compile("(?i)Entry\\s*Range\\s*:\\s*([0-9]+(?:\\.[0-9]+)?)\\s*[-–]\\s*([0-9]+(?:\\.[0-9]+)?)");
    private static final Pattern STOP = Pattern.compile("(?i)Stop\\s*Loss\\s*:\\s*([0-9]+(?:\\.[0-9]+)?)");

    @Override public void onNotificationPosted(StatusBarNotification sbn) {
        TradingEngine e = FastBuyApp.get().engine();
        if (!e.isArmed()) return;
        String text = extract(sbn.getNotification());
        String low = text.toLowerCase(Locale.ROOT);
        String pkg = sbn.getPackageName() == null ? "" : sbn.getPackageName().toLowerCase(Locale.ROOT);
        boolean looksMultyfi = pkg.contains("multyfi") || pkg.contains("multify") || low.contains("released: equity intraday trade");
        if (!looksMultyfi) return;

        if (low.contains("released: equity intraday trade") || low.contains("released:equity intraday trade")) {
            Call c = parseCall(text);
            if (c != null) e.onNewCall(c, sbn.getPostTime());
            return;
        }

        String active = e.activeSymbol();
        if (active.isEmpty() || !low.contains(active.toLowerCase(Locale.ROOT))) return;
        if (isAuthoritativeEarlyExit(low)) e.onMultyfiEarlyExit(active, compact(text));
    }

    private static boolean isAuthoritativeEarlyExit(String s) {
        return s.contains("close early") || s.contains("closing early") ||
               s.contains("book profit") || s.contains("book profits") ||
               s.contains("protect profit and exit") || s.contains("exit all") ||
               s.contains("early exit");
    }

    private static Call parseCall(String s) {
        Matcher ms=STOCK.matcher(s), mt=TARGET.matcher(s), mr=RANGE.matcher(s), mp=STOP.matcher(s);
        if(!ms.find() || !mt.find() || !mr.find()) return null;
        String symbol=ms.group(1).trim().replaceAll("\\s+", "").toUpperCase(Locale.ROOT);
        try {
            double target=Double.parseDouble(mt.group(1));
            double a=Double.parseDouble(mr.group(1)), b=Double.parseDouble(mr.group(2));
            double stop=mp.find()?Double.parseDouble(mp.group(1)):0;
            return new Call(symbol,target,Math.min(a,b),Math.max(a,b),stop);
        } catch(Exception ex){ return null; }
    }

    private static String extract(Notification n) {
        if(n==null || n.extras==null) return "";
        StringBuilder b=new StringBuilder();
        add(b,n.extras.getCharSequence(Notification.EXTRA_TITLE));
        add(b,n.extras.getCharSequence(Notification.EXTRA_TEXT));
        add(b,n.extras.getCharSequence(Notification.EXTRA_BIG_TEXT));
        CharSequence[] lines=n.extras.getCharSequenceArray(Notification.EXTRA_TEXT_LINES);
        if(lines!=null) for(CharSequence x:lines) add(b,x);
        return b.toString();
    }
    private static void add(StringBuilder b,CharSequence s){if(s!=null&&s.length()>0)b.append(s).append('\n');}
    private static String compact(String s){s=s.replace('\n',' ').replace('\r',' ').trim();return s.length()>120?s.substring(0,120):s;}
}
