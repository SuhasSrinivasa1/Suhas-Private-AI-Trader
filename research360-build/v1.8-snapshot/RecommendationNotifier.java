package com.suhas.research360engine;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.os.Build;

import java.util.Locale;

/** User-visible, one-shot BUY recommendation notification. Tapping BUY opens amount entry in MainActivity. */
public final class RecommendationNotifier {
    public static final String CHANNEL="r360_buy_recommendations";
    public static final String EXTRA_SIGNAL_ID="buy_signal_id";
    private RecommendationNotifier(){}

    public static void notifyBuy(Context c,Db.Signal s,double score,double ourEntry){
        if(c==null||s==null||s.id<=0||AppState.buyNotified(c,s.id))return;
        NotificationManager nm=(NotificationManager)c.getSystemService(Context.NOTIFICATION_SERVICE);if(nm==null)return;
        if(Build.VERSION.SDK_INT>=26){NotificationChannel ch=new NotificationChannel(CHANNEL,"Research360 BUY recommendations",NotificationManager.IMPORTANCE_HIGH);ch.setDescription("Qualified Research360 Intelligence BUY recommendations requiring your action");ch.enableVibration(true);nm.createNotificationChannel(ch);}
        Intent i=new Intent(c,MainActivity.class).putExtra(EXTRA_SIGNAL_ID,s.id).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK|Intent.FLAG_ACTIVITY_SINGLE_TOP|Intent.FLAG_ACTIVITY_CLEAR_TOP);
        int flags=PendingIntent.FLAG_UPDATE_CURRENT|(Build.VERSION.SDK_INT>=23?PendingIntent.FLAG_IMMUTABLE:0);PendingIntent pi=PendingIntent.getActivity(c,(int)(s.id%Integer.MAX_VALUE),i,flags);
        String title="BUY candidate: "+s.symbol;String text=String.format(Locale.US,"Our score %.0f%% • entry ~₹%.2f • tap BUY to enter rupee amount",score,ourEntry);
        Notification.Builder b=Build.VERSION.SDK_INT>=26?new Notification.Builder(c,CHANNEL):new Notification.Builder(c);
        b.setSmallIcon(android.R.drawable.ic_input_add).setContentTitle(title).setContentText(text).setStyle(new Notification.BigTextStyle().bigText(text+"\nResearch360 target is ignored; our model manages target/exit.")).setContentIntent(pi).setAutoCancel(true).setPriority(Notification.PRIORITY_HIGH).addAction(android.R.drawable.ic_input_add,"BUY",pi);
        nm.notify(50000+(int)(s.id%10000),b.build());AppState.setBuyNotified(c,s.id);
    }
}
