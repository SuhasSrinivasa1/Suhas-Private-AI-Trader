package com.suhas.research360engine;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.os.Build;
import android.os.IBinder;

import java.time.LocalTime;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

public final class EngineService extends Service {
    public static final String ACTION_UI="com.suhas.research360engine.UI_UPDATE";
    private static final String CHANNEL="r360_engine";private static final int NOTIF_ID=3601;private static final ZoneId IST=ZoneId.of("Asia/Kolkata");
    private ScheduledExecutorService scheduler,ipScheduler,healthScheduler;private GrowwClient groww;private Db db;private StrategyEngine strategy;private IpGuard ipGuard;
    private final AtomicBoolean runningTick=new AtomicBoolean(false);private long lastCredentialLog=0,lastErrorLog=0,lastPositionCheck=0;

    @Override public void onCreate(){
        super.onCreate();LearningBackup.autoRestoreIfFresh(this); db=Db.get(this);AppState.migrateV14(this,db.rawNotificationCount());db.purgeLegacyNotificationNoise();db.disableRemovedEngines();groww=new GrowwClient(this);strategy=new StrategyEngine(this);ipGuard=new IpGuard(this);createChannel();startForeground(NOTIF_ID,buildNotification("Armed for validated Research360 learning • Live orders OFF"));
        scheduler=Executors.newSingleThreadScheduledExecutor(r->daemon(r,"R360-Engine"));scheduler.scheduleWithFixedDelay(this::tickSafe,1,3,TimeUnit.SECONDS);
        ipScheduler=Executors.newSingleThreadScheduledExecutor(r->daemon(r,"R360-IPGuard"));ipScheduler.scheduleWithFixedDelay(this::ipSafe,3,45,TimeUnit.SECONDS);
        healthScheduler=Executors.newSingleThreadScheduledExecutor(r->daemon(r,"R360-ApiHealth"));healthScheduler.scheduleWithFixedDelay(this::healthSafe,5,300,TimeUnit.SECONDS);
        db.log("INFO","Research360 Intelligence v1.8 engine started • notification dedupe + Groww sector oracle + auto IP/API health");
    }
    private static Thread daemon(Runnable r,String n){Thread t=new Thread(r,n);t.setDaemon(true);return t;}
    @Override public int onStartCommand(Intent intent,int flags,int startId){return START_STICKY;}@Override public IBinder onBind(Intent intent){return null;}@Override public void onDestroy(){for(ScheduledExecutorService s:new ScheduledExecutorService[]{scheduler,ipScheduler,healthScheduler})if(s!=null)s.shutdownNow();super.onDestroy();}

    private void tickSafe(){if(!runningTick.compareAndSet(false,true))return;try{tick();}catch(Exception e){throttledError("Engine: "+shortMsg(e));}finally{try{LearningBackup.maybeBackup(this);}catch(Exception ignored){}runningTick.set(false);}}

    private void healthSafe(){if(!groww.hasCredentials())return;try{GrowwClient.Health h=groww.validate(false);if(h.ok)db.log("API-HEALTH","CONNECTED • paid NSE CASH/live data validated");}catch(Exception first){try{groww.clearToken();GrowwClient.Health h=groww.validate(true);if(h.ok)db.log("API-HEALTH","CONNECTED • authentication auto-refreshed");}catch(Exception second){db.log("API-HEALTH","DISCONNECTED • "+shortMsg(second));if(AppState.liveOrders(this)){AppState.setLiveOrders(this,false);db.log("RISK","AUTO LIVE disabled because Groww API validation failed");}broadcast();}}}
    private void ipSafe(){
        if(!AppState.isArmed(this)&&!AppState.liveOrders(this))return;if(AppState.expectedStaticIp(this).isEmpty())return;
        try{IpGuard.Status s=ipGuard.verifyNow();if(!s.verified&&AppState.liveOrders(this)){AppState.setLiveOrders(this,false);db.log("IP-GUARD","AUTO LIVE disabled: "+s.reason+" • current "+(s.publicIp.isEmpty()?"unknown":s.publicIp));}broadcast();}
        catch(Exception e){if(AppState.liveOrders(this))AppState.setLiveOrders(this,false);}
    }

    private void tick()throws Exception{
        Db.Stats stats=db.stats();int rc=stats.r360Confidence();
        if(!AppState.isArmed(this)){protectLiveTradeOnly();updateForeground("DISARMED • new signals paused • live-position safety remains active");broadcast();return;}
        if(!groww.hasCredentials()){if(System.currentTimeMillis()-lastCredentialLog>60000){db.log("WARN","Groww credentials missing — validated notifications still captured; analysis paused");lastCredentialLog=System.currentTimeMillis();}updateForeground("ARMED • waiting for Groww credentials • Live OFF");broadcast();return;}
        if(stats.liveNetToday<=-AppState.dailyLossLimit(this)&&AppState.liveOrders(this)){AppState.setLiveOrders(this,false);db.log("RISK","₹"+String.format(Locale.US,"%.0f",AppState.dailyLossLimit(this))+" daily loss ceiling reached — AUTO LIVE disabled");}

        List<Db.Signal> signals=db.activeSignals();if(signals.isEmpty()){reconcileLiveTradeOnly();updateForeground(statusText(rc,stats));broadcast();return;}
        ArrayList<String> syms=new ArrayList<>();for(Db.Signal s:signals)if(!s.symbol.isEmpty()&&!syms.contains(s.symbol))syms.add(s.symbol);Map<String,Double> ltps=groww.getLtps(syms);int fullQuotes=0;
        for(Db.Signal s:signals){double ltp=ltps.containsKey(s.symbol)?ltps.get(s.symbol):0;if(ltp<=0)continue;updateExcursions(s,ltp);Db.Trade open=db.openTradeForSignal(s.id);if(expireIfNeeded(s,open))continue;boolean near=s.entry<=0||Math.abs((ltp/s.entry-1)*100)<=1.35||open!=null;if(!near){if("NEW".equals(s.status))db.updateSignal(s.id,"WATCH",s.score,s.firstLtp>0?s.firstLtp:ltp,s.mfe,s.mae);continue;}if(fullQuotes>=7&&open==null)continue;Db.MarketSnapshot q=groww.getQuote(s.symbol);fullQuotes++;process(s,q,open);}
        reconcileLiveTradeOnly();stats=db.stats();updateForeground(statusText(stats.r360Confidence(),stats));broadcast();
    }

    private void process(Db.Signal s,Db.MarketSnapshot q,Db.Trade open)throws Exception{
        if(q.ltp<=0)return;if(s.firstLtp<=0)s.firstLtp=q.ltp;double sc=strategy.score(s,q);db.insertSnapshot(s.id,q,sc);updateExcursions(s,q.ltp);s=db.getSignal(s.id);if(s==null)return;db.updateSignal(s.id,s.status,sc,s.firstLtp,s.mfe,s.mae);open=db.openTradeForSignal(s.id);if(open!=null){manageOpen(s,open,q,sc);return;}
        if(!strategy.triggerReached(s,q.ltp)){if(!"WATCH".equals(s.status))db.setSignalStatus(s.id,"WATCH");return;}if(!strategy.entryNearEnough(s,q.ltp)){db.setSignalStatus(s.id,"WATCH");return;}int qty=strategy.quantityFor(q.ltp);if(qty<=0){db.setSignalStatus(s.id,"REJECTED");return;}double threshold=Math.max(82.0,strategy.qualifyThreshold(s));if(sc<threshold){db.setSignalStatus(s.id,"WATCH");return;}String analystWhy=analystRejectReason(s,q,sc);if(!analystWhy.isEmpty()){db.setSignalStatus(s.id,"WATCH");db.log("ANALYST-FILTER",s.symbol+" held internally: "+analystWhy);return;}String product=strategy.product(s);if(!strategy.economicallyFeasible(q.ltp,qty,product,sc)){db.setSignalStatus(s.id,"REJECTED");db.log("FILTER",String.format(Locale.US,"%s rejected: ₹100 net needs %.2f%% at configured budget",s.symbol,strategy.requiredNet100MovePct(q.ltp,qty,product)));return;}

        // A qualifying idea is useful to the user even while autonomous execution is evidence-locked.
        RecommendationNotifier.notifyBuy(this,s,sc,q.ltp);

        Db.Stats stats=db.stats();boolean sourceGate=sourceGate(stats,s.category);boolean live=AppState.liveOrders(this)&&sourceGate&&marketOpenForEntry(product)&&db.openLiveTrade()==null;
        if(live&&!guardsHealthyNow(s.symbol))live=false;
        if(live){GrowwClient.OrderResult r=groww.placeMarket(s.symbol,qty,product,"BUY");ensureAccepted(r);Fill fill=awaitFill(r.orderId,q.ltp,false);if(fill.qty<=0)throw new IllegalStateException("Groww BUY not filled");long tid=db.openTrade(s.id,s.symbol,s.category,"LIVE",fill.qty,fill.price,sc,r.orderId);db.setSignalStatus(s.id,"LIVE_ACTIVE");armProfitGtt(tid,s,fill.qty,fill.price,sc,q);db.log("LIVE",String.format(Locale.US,"BUY %s x%d @ ~₹%.2f • score %.0f",s.symbol,fill.qty,fill.price,sc));}
        else{db.openTrade(s.id,s.symbol,s.category,"SHADOW",qty,q.ltp,sc,"");db.setSignalStatus(s.id,"SHADOW_ACTIVE");db.log("PAPER",String.format(Locale.US,"Shadow BUY %s x%d @ ₹%.2f • score %.0f • %s",s.symbol,qty,q.ltp,sc,sourceName(s.category)));}
    }

    private String analystRejectReason(Db.Signal s,Db.MarketSnapshot q,double score){
        if(q.ltp<=0)return "no live price";
        if(q.spreadBps>25)return String.format(Locale.US,"spread %.1fbps too wide",q.spreadBps);
        if(q.depthImbalance<-.15)return String.format(Locale.US,"seller-heavy depth %.2f",q.depthImbalance);
        if(q.averagePrice>0){double ext=(q.ltp/q.averagePrice-1)*100.0;if(ext>1.8)return String.format(Locale.US,"late/extended %.2f%% above average price",ext);if(ext<-.35)return String.format(Locale.US,"below average price %.2f%%",ext);}
        if(q.rangePosition>.95&&q.dayChangePct>1.5)return String.format(Locale.US,"late chase near day high (range %.0f%%)",q.rangePosition*100.0);
        if(q.dayChangePct>5.0)return String.format(Locale.US,"already up %.2f%% today",q.dayChangePct);
        if(!"MOST_OVERNIGHT".equals(s.category)&&System.currentTimeMillis()-s.ts>45L*60L*1000L)return "intraday call is stale (>45 min)";
        return "";
    }

    private boolean guardsHealthyNow(String symbol){
        try{if(!AppState.apiHealthyFresh(this,10L*60L*1000L)){GrowwClient.Health h=groww.validate(false);if(!h.ok)return false;}if(!ipGuard.cachedVerified(180000)){IpGuard.Status ips=ipGuard.verifyNow();if(!ips.verified){AppState.setLiveOrders(this,false);db.log("IP-GUARD","BUY blocked for "+symbol+": "+ips.reason);return false;}}return true;}catch(Exception e){AppState.setLiveOrders(this,false);db.log("API-GUARD","BUY blocked for "+symbol+": "+shortMsg(e));return false;}
    }
    private boolean sourceGate(Db.Stats s,String c){return s.r360GateReady();}

    private void armProfitGtt(long tradeId,Db.Signal s,int qty,double entry,double score,Db.MarketSnapshot q){try{double target=strategy.realisticTarget(entry,qty,strategy.product(s),score,q);GrowwClient.SmartOrderResult g=groww.placeGttSell(s.symbol,qty,strategy.product(s),target);AppState.setTradeGtt(this,tradeId,g.smartOrderId);db.log("GTT",String.format(Locale.US,"%s profit GTT armed x%d @ ₹%.2f • OUR target",s.symbol,qty,target));}catch(Exception e){db.log("GTT","Unable to arm broker profit GTT for "+s.symbol+": "+shortMsg(e)+" • app trailing protection remains active");}}
    private void cancelTradeGtt(Db.Trade t){String id=AppState.tradeGtt(this,t.id);if(id.isEmpty())return;try{groww.cancelGtt(id);}catch(Exception ignored){}AppState.clearTradeGtt(this,t.id);}

    private void manageOpen(Db.Signal s,Db.Trade t,Db.MarketSnapshot q,double score)throws Exception{
        if(q.ltp>t.peak){db.updatePeak(t.id,q.ltp);t.peak=q.ltp;}if("LIVE".equals(t.mode)&&System.currentTimeMillis()-lastPositionCheck>4500){lastPositionCheck=System.currentTimeMillis();GrowwClient.Position p=groww.getPosition(t.symbol,strategy.product(s));if(p.quantity<=0){cancelTradeGtt(t);double gross=(q.ltp-t.entry)*t.qty,ch=StrategyEngine.charges(t.entry,q.ltp,t.qty,strategy.product(s));db.closeTrade(t.id,q.ltp,gross,ch,gross-ch,"BROKER_OR_MANUAL_EXIT");db.setSignalStatus(s.id,"MANUAL_EXIT");db.log("MANUAL","Groww position is zero for "+t.symbol+" — strategy closed; no re-entry");return;}}
        StrategyEngine.ExitDecision d=strategy.exitDecision(s,t,q,score);if(!d.exit)return;if("LIVE".equals(t.mode)){cancelTradeGtt(t);GrowwClient.OrderResult r=groww.placeMarket(t.symbol,t.qty,strategy.product(s),"SELL");ensureAccepted(r);Fill fill=awaitFill(r.orderId,q.ltp,false);if(fill.qty<=0)throw new IllegalStateException("Groww SELL not filled");close(t,s,fill.price,d.reason);db.log("LIVE",String.format(Locale.US,"SELL %s x%d @ ~₹%.2f • %s",t.symbol,t.qty,fill.price,d.reason));}else close(t,s,q.ltp,d.reason);
    }
    private void close(Db.Trade t,Db.Signal s,double exit,String reason){double gross=(exit-t.entry)*t.qty,ch=StrategyEngine.charges(t.entry,exit,t.qty,strategy.product(s)),net=gross-ch;db.closeTrade(t.id,exit,gross,ch,net,reason);db.setSignalStatus(s.id,"DONE");db.log("RESULT",String.format(Locale.US,"%s %s net ₹%.2f (gross ₹%.2f, est. charges ₹%.2f)",t.mode,t.symbol,net,gross,ch));}

    private void ensureAccepted(GrowwClient.OrderResult r){if(r==null||r.orderId==null||r.orderId.isEmpty())throw new IllegalStateException("Groww order not accepted");String st=r.status==null?"":r.status.toUpperCase(Locale.ROOT);if(st.contains("REJECT")||st.contains("CANCEL")||st.contains("FAIL"))throw new IllegalStateException("Groww order "+st+(r.remark==null?"":" • "+r.remark));}
    private Fill awaitFill(String orderId,double fallback,boolean cancelRemainder){Fill f=new Fill();for(int i=0;i<8;i++)try{Thread.sleep(i==0?300:500);GrowwClient.OrderDetail d=groww.getOrderDetail(orderId);if(d.filledQty>0){f.qty=d.filledQty;f.price=d.averageFillPrice>0?d.averageFillPrice:fallback;if(d.remainingQty<=0||isTerminal(d.status))return f;}if(isFailed(d.status))return f;}catch(InterruptedException e){Thread.currentThread().interrupt();break;}catch(Exception e){if(i==7)db.log("WARN","Fill confirmation: "+shortMsg(e));}if(cancelRemainder)try{groww.cancelOrder(orderId);}catch(Exception ignored){}return f;}
    private static boolean isFailed(String s){if(s==null)return false;s=s.toUpperCase(Locale.ROOT);return s.contains("REJECT")||s.contains("CANCEL")||s.contains("FAIL");}private static boolean isTerminal(String s){if(s==null)return false;s=s.toUpperCase(Locale.ROOT);return s.contains("COMPLETE")||s.contains("EXECUTED")||s.contains("FILLED");}
    private void updateExcursions(Db.Signal s,double ltp){double ref=s.entry>0?s.entry:s.firstLtp;if(ref<=0){db.updateSignal(s.id,s.status,s.score,ltp,s.mfe,s.mae);return;}if(s.entry>0&&ltp<s.entry&&s.mfe==0&&s.mae==0)return;double pct=(ltp/ref-1)*100,mfe=Math.max(s.mfe,pct),mae=Math.min(s.mae,pct);db.updateSignal(s.id,s.status,s.score,s.firstLtp>0?s.firstLtp:ltp,mfe,mae);}
    private boolean expireIfNeeded(Db.Signal s,Db.Trade open){LocalTime now=LocalTime.now(IST);boolean intraday=!"MOST_OVERNIGHT".equals(s.category);if(open==null&&intraday&&now.isAfter(LocalTime.of(15,16))){db.setSignalStatus(s.id,"EXPIRED");return true;}if(open==null&&System.currentTimeMillis()-s.ts>30L*60L*60L*1000L){db.setSignalStatus(s.id,"EXPIRED");return true;}return false;}
    private boolean marketOpenForEntry(String product){LocalTime n=LocalTime.now(IST);return !n.isBefore(LocalTime.of(9,15))&&n.isBefore("MIS".equals(product)?LocalTime.of(15,10):LocalTime.of(15,20));}

    private void protectLiveTradeOnly(){Db.Trade t=db.openLiveTrade();if(t==null||!groww.hasCredentials())return;try{Db.Signal s=db.getSignal(t.signalId);if(s==null)return;Db.MarketSnapshot q=groww.getQuote(t.symbol);double sc=strategy.score(s,q);if(q.ltp>t.peak){db.updatePeak(t.id,q.ltp);t.peak=q.ltp;}StrategyEngine.ExitDecision d=strategy.exitDecision(s,t,q,sc);if(d.exit){cancelTradeGtt(t);GrowwClient.OrderResult r=groww.placeMarket(t.symbol,t.qty,strategy.product(s),"SELL");ensureAccepted(r);Fill f=awaitFill(r.orderId,q.ltp,false);if(f.qty>0){close(t,s,f.price,"DISARMED_SAFETY_"+d.reason);db.log("RISK","Protective exit while disarmed: "+t.symbol);}}else reconcileLiveTradeOnly();}catch(Exception e){throttledError("Disarmed live protection: "+shortMsg(e));}}
    private void reconcileLiveTradeOnly(){Db.Trade t=db.openLiveTrade();if(t==null||!groww.hasCredentials())return;try{Db.Signal s=db.getSignal(t.signalId);if(s==null)return;GrowwClient.Position p=groww.getPosition(t.symbol,strategy.product(s));if(p.quantity<=0){cancelTradeGtt(t);Db.MarketSnapshot q=groww.getQuote(t.symbol);double exit=q.ltp>0?q.ltp:t.entry,gross=(exit-t.entry)*t.qty,ch=StrategyEngine.charges(t.entry,exit,t.qty,strategy.product(s));db.closeTrade(t.id,exit,gross,ch,gross-ch,"BROKER_OR_MANUAL_EXIT");db.setSignalStatus(s.id,"MANUAL_EXIT");db.log("MANUAL","External/manual/GTT exit detected for "+t.symbol);}}catch(Exception e){throttledError("Live reconciliation: "+shortMsg(e));}}

    private String statusText(int r,Db.Stats s){String live=AppState.liveOrders(this)?"AUTO LIVE ENABLED":"AUTO LIVE OFF";String ip=ipGuard.cachedVerified(180000)?"IP VERIFIED":"IP CHECK";return "ARMED • "+live+" • R360 "+r+"% • "+ip;}
    private String sourceName(String c){return"R360 FILTER";}
    private void createChannel(){if(Build.VERSION.SDK_INT>=26){NotificationChannel c=new NotificationChannel(CHANNEL,"Research360 Engine",NotificationManager.IMPORTANCE_LOW);c.setDescription("Research360 notification analysis, static-IP guard and trading safety status");getSystemService(NotificationManager.class).createNotificationChannel(c);}}
    private Notification buildNotification(String text){Notification.Builder b=Build.VERSION.SDK_INT>=26?new Notification.Builder(this,CHANNEL):new Notification.Builder(this);return b.setContentTitle("Research360 Intelligence v1.8").setContentText(text).setSmallIcon(android.R.drawable.ic_menu_info_details).setOngoing(true).build();}
    private void updateForeground(String s){getSystemService(NotificationManager.class).notify(NOTIF_ID,buildNotification(s));}private void broadcast(){sendBroadcast(new Intent(ACTION_UI).setPackage(getPackageName()));}private void throttledError(String m){if(System.currentTimeMillis()-lastErrorLog>30000){db.log("ERROR",m);lastErrorLog=System.currentTimeMillis();}}private static String shortMsg(Exception e){String s=e.getMessage();return s==null?e.getClass().getSimpleName():s.substring(0,Math.min(300,s.length()));}
    private static final class Fill{int qty;double price;}
}
