package com.suhas.multyfifastbuy;

import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.os.Build;
import android.os.IBinder;

import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

public class TradingMonitorService extends Service {
    private static final String CH="fastbuy_core";
    private ScheduledExecutorService timer;
    private int uiTick;

    @Override public void onCreate(){
        super.onCreate();
        NotificationManager nm=getSystemService(NotificationManager.class);
        if(Build.VERSION.SDK_INT>=26){NotificationChannel c=new NotificationChannel(CH,"Multyfi FastBuy Core",NotificationManager.IMPORTANCE_LOW);c.setDescription("FastBuy armed monitor");nm.createNotificationChannel(c);}
        startForeground(1401, notification());
        timer=Executors.newSingleThreadScheduledExecutor(r->{Thread t=new Thread(r,"FastBuyMonitorTimer");t.setDaemon(true);return t;});
        timer.scheduleAtFixedRate(()->{
            TradingEngine e=FastBuyApp.get().engine();
            e.monitorTick();
            if(++uiTick>=20){uiTick=0;try{nm.notify(1401,notification());}catch(Exception ignored){}}
        },0,250, TimeUnit.MILLISECONDS);
    }

    private android.app.Notification notification(){
        Intent i=new Intent(this,MainActivity.class);
        PendingIntent pi=PendingIntent.getActivity(this,3,i,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
        return new android.app.Notification.Builder(this,CH)
                .setSmallIcon(android.R.drawable.ic_media_play)
                .setContentTitle("Multyfi FastBuy Core")
                .setContentText(FastBuyApp.get().engine().statusText())
                .setOngoing(true).setContentIntent(pi).build();
    }

    @Override public int onStartCommand(Intent i,int flags,int id){return START_STICKY;}
    @Override public void onDestroy(){if(timer!=null)timer.shutdownNow();super.onDestroy();}
    @Override public IBinder onBind(Intent i){return null;}
}
