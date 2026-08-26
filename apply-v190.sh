#!/usr/bin/env bash
set -euo pipefail
cd nse-intraday-v180
python3 - <<'PY'
from pathlib import Path
# version
p=Path('app/build.gradle');s=p.read_text();s=s.replace('versionCode 180','versionCode 190').replace("versionName '1.8.0'","versionName '1.9.0'");p.write_text(s)
# LearningStore hourly grading
p=Path('app/src/main/java/com/suhas/nsedeliverymomentum/LearningStore.java');s=p.read_text()
s=s.replace('''    synchronized void update(String symbol,double price){
        for(Call c:new ArrayList<>(active.values())){
            if(!c.symbol.equals(symbol)||!"OPEN".equals(c.state))continue;c.high=Math.max(c.high,price);c.low=Math.min(c.low,price);
            boolean hit="SHORT".equals(c.direction)?price<=c.entry*0.99:price>=c.entry*1.01;
            if(hit){c.state="HIT";increment("hits");increment("resolved");recordBucket(c,true);active.remove(c.key());}
        }
        save();
    }''','''    synchronized void update(String symbol,double price){
        long now=System.currentTimeMillis();
        for(Call c:new ArrayList<>(active.values())){
            if(!"OPEN".equals(c.state))continue;
            if(now-c.time>=60L*60L*1000L){c.state="MISS";increment("resolved");incrementHour(c,"resolved");recordBucket(c,false);active.remove(c.key());continue;}
            if(!c.symbol.equals(symbol))continue;c.high=Math.max(c.high,price);c.low=Math.min(c.low,price);
            boolean hit="SHORT".equals(c.direction)?price<=c.entry*0.99:price>=c.entry*1.01;
            if(hit){c.state="HIT";increment("hits");increment("resolved");incrementHour(c,"hits");incrementHour(c,"resolved");recordBucket(c,true);active.remove(c.key());}
        }
        save();
    }''')
s=s.replace('synchronized void resolveEndOfDay(){for(Call c:new ArrayList<>(active.values())){c.state="MISS";increment("resolved");recordBucket(c,false);}active.clear();save();}','synchronized void resolveEndOfDay(){for(Call c:new ArrayList<>(active.values())){c.state="MISS";increment("resolved");incrementHour(c,"resolved");recordBucket(c,false);}active.clear();save();}')
s=s.replace('int hitsToday(){rollDay();return p.getInt("today_hits",0);}int resolvedToday(){rollDay();return p.getInt("today_resolved",0);}int callsToday(){rollDay();return p.getInt("today_calls",0);}void noteCall(){rollDay();p.edit().putInt("today_calls",p.getInt("today_calls",0)+1).apply();}', '''int hitsToday(){rollDay();return p.getInt("today_hits",0);}int resolvedToday(){rollDay();return p.getInt("today_resolved",0);}int callsToday(){rollDay();return p.getInt("today_calls",0);}void noteCall(){rollDay();p.edit().putInt("today_calls",p.getInt("today_calls",0)+1).apply();incrementHourNow("calls");}
    int hitsCurrentHour(){return p.getInt(hourKey(System.currentTimeMillis())+"_hits",0);}
    int resolvedCurrentHour(){return p.getInt(hourKey(System.currentTimeMillis())+"_resolved",0);}
    int callsCurrentHour(){return p.getInt(hourKey(System.currentTimeMillis())+"_calls",0);}
    private void incrementHour(Call c,String what){String k=hourKey(c.time)+"_"+what;p.edit().putInt(k,p.getInt(k,0)+1).apply();}
    private void incrementHourNow(String what){String k=hourKey(System.currentTimeMillis())+"_"+what;p.edit().putInt(k,p.getInt(k,0)+1).apply();}
    private String hourKey(long ms){java.time.ZonedDateTime z=java.time.Instant.ofEpochMilli(ms).atZone(java.time.ZoneId.of("Asia/Kolkata"));return String.format(java.util.Locale.US,"h_%04d%02d%02d_%02d",z.getYear(),z.getMonthValue(),z.getDayOfMonth(),z.getHour());}''')
p.write_text(s)
# Service adaptive integration
p=Path('app/src/main/java/com/suhas/nsedeliverymomentum/DeliveryMomentumService.java');s=p.read_text()
s=s.replace('private SecretStore store; private GrowwClient api; private LearningStore learning; private UniverseStore.Universe universe; private NightLab nightLab;','private SecretStore store; private GrowwClient api; private LearningStore learning; private UniverseStore.Universe universe; private NightLab nightLab; private HourlyAdaptiveLearning hourlyLearning;')
s=s.replace('super.onCreate();store=new SecretStore(this);api=new GrowwClient(store);learning=new LearningStore(this);Housekeeping.runDaily(this,store);','super.onCreate();store=new SecretStore(this);api=new GrowwClient(store);learning=new LearningStore(this);hourlyLearning=new HourlyAdaptiveLearning(learning,store);Housekeeping.runDaily(this,store);')
s=s.replace('''        List<Map.Entry<String,GrowwClient.Ohlc>> movers=buildContinuationPool(snap);
        int broadMoverCount=movers.size();
        List<Map.Entry<String,GrowwClient.Ohlc>> trajectoryPool=buildTrajectoryPool(snap);
        List<Map.Entry<String,GrowwClient.Ohlc>> breakdownPool=buildBreakdownPool(snap);
        monitorActive(snap);

        long sinceDeep=System.currentTimeMillis()-lastDeep;
        if(sinceDeep<90000){long next=Math.max(0,(90000-sinceDeep)/1000);''','''        HourlyAdaptiveLearning.State adaptive=hourlyLearning.state();
        List<Map.Entry<String,GrowwClient.Ohlc>> movers=buildContinuationPool(snap);
        int broadMoverCount=movers.size();
        List<Map.Entry<String,GrowwClient.Ohlc>> trajectoryPool=buildTrajectoryPool(snap);
        List<Map.Entry<String,GrowwClient.Ohlc>> breakdownPool=buildBreakdownPool(snap);
        monitorActive(snap);

        long sinceDeep=System.currentTimeMillis()-lastDeep;
        if(sinceDeep<adaptive.deepIntervalMs){long next=Math.max(0,(adaptive.deepIntervalMs-sinceDeep)/1000);''')
s=s.replace('next confirm %ds",valid,syms.size(),breadth*100,movers.size()+trajectoryPool.size(),breakdownPool.size(),next);','next confirm %ds • %s",valid,syms.size(),breadth*100,movers.size()+trajectoryPool.size(),breakdownPool.size(),next,adaptive.summary());')
s=s.replace('Math.min(100,movers.size())','Math.min(100+adaptive.poolBoost,movers.size())').replace('Math.min(55,trajectoryPool.size())','Math.min(55+adaptive.poolBoost,trajectoryPool.size())').replace('Math.min(65,breakdownPool.size())','Math.min(65+adaptive.poolBoost,breakdownPool.size())')
s=s.replace('applyLongConfirmation(out,trajOut);','applyLongConfirmation(out,trajOut,adaptive);').replace('applyShortConfirmation(shortOut);','applyShortConfirmation(shortOut,adaptive);')
s=s.replace('private void applyLongConfirmation(List<Candidate> out,List<TrajectoryCandidate> traj){','private void applyLongConfirmation(List<Candidate> out,List<TrajectoryCandidate> traj,HourlyAdaptiveLearning.State adaptive){')
s=s.replace('int contFloor=store.getInt("night_cont_floor",80),contScans=store.getInt("night_cont_scans",3),trajFloor=store.getInt("night_traj_floor",68),trajScans=store.getInt("night_traj_scans",3);','int contFloor=store.getInt("night_cont_floor",80),contScans=store.getInt("night_cont_scans",3),trajFloor=store.getInt("night_traj_floor",68),trajScans=store.getInt("night_traj_scans",3);if(adaptive.acceleratedConfirmation){contScans=Math.max(2,contScans-1);trajScans=Math.max(2,trajScans-1);}')
s=s.replace('private void applyShortConfirmation(List<BreakdownCandidate> out){','private void applyShortConfirmation(List<BreakdownCandidate> out,HourlyAdaptiveLearning.State adaptive){').replace('int floor=store.getInt("night_short_floor",78),need=store.getInt("night_short_scans",3);','int floor=store.getInt("night_short_floor",78),need=store.getInt("night_short_scans",3);if(adaptive.acceleratedConfirmation)need=Math.max(2,need-1);')
s=s.replace('pending %d • %s",valid,syms.size(),buys,up,shorts,confirming,now.toLocalTime().withNano(0));','pending %d • %s • %s",valid,syms.size(),buys,up,shorts,confirming,now.toLocalTime().withNano(0),adaptive.summary());')
s=s.replace('i.putExtra("storage_report",Housekeeping.summary(this,store));sendBroadcast(i);','i.putExtra("storage_report",Housekeeping.summary(this,store));i.putExtra("hourly_report",HourlyAdaptiveLearning.storedSummary(store));sendBroadcast(i);')
p.write_text(s)
# UI
p=Path('app/src/main/java/com/suhas/nsedeliverymomentum/MainActivity.java');s=p.read_text()
s=s.replace('nightReport,storageReport;','nightReport,storageReport,hourlyReport;')
s=s.replace('3-engine INTRADAY scanner + NIGHT LAB + confirmed alerts','3-engine INTRADAY scanner + HOURLY ADAPT + NIGHT LAB')
s=s.replace('Three independent intraday engines: two LONG engines and one SHORT engine. Confirmed signals include ENTRY and TARGET notifications. NIGHT LAB adapts validated score/persistence gates while housekeeping keeps learning storage bounded.','Three intraday engines: two LONG and one SHORT. Hourly Adapt targets 5 resolved wins per market hour and increases learning/search intensity when behind, while preserving minimum quality floors. Confirmed signals include ENTRY and TARGET notifications.')
s=s.replace('benchValue=metric(m2,"MODE","STRICT","no forced daily quota",amber);','benchValue=metric(m2,"MODE","ADAPT","5 wins/hour target",amber);')
anchor='benchmarkBar=new ProgressBar(this,null,android.R.attr.progressBarStyleHorizontal);benchmarkBar.setMax(1);benchmarkBar.setProgress(1);benchmarkBar.setProgressTintList(ColorStateList.valueOf(green));benchmarkBar.setProgressBackgroundTintList(ColorStateList.valueOf(surface2));LinearLayout.LayoutParams bp=new LinearLayout.LayoutParams(-1,dp(5));bp.setMargins(dp(2),dp(4),dp(2),dp(16));root.addView(benchmarkBar,bp);'
insert=anchor+'\n\n        LinearLayout hourly=column();hourly.setPadding(dp(17),dp(13),dp(17),dp(13));hourly.setBackground(round(surface2,dp(16),amber,1));hourly.addView(label("HOURLY ADAPTIVE LEARNING • TARGET 5 WINS",12,amber,true));hourlyReport=label(HourlyAdaptiveLearning.storedSummary(store),11,text,false);hourlyReport.setPadding(0,dp(5),0,0);hourly.addView(hourlyReport);TextView hourlySub=label("When the hour is behind target, scan cadence, candidate breadth and learning intensity increase automatically. Score-quality floors stay protected; weak calls are not fabricated to fill the quota.",10,muted,false);hourlySub.setPadding(0,dp(6),0,0);hourly.addView(hourlySub);LinearLayout.LayoutParams hp=new LinearLayout.LayoutParams(-1,-2);hp.setMargins(0,0,0,dp(14));root.addView(hourly,hp);'
assert anchor in s;s=s.replace(anchor,insert)
s=s.replace('No automatic order is sent in v1.8.0.','No automatic order is sent in v1.9.0.')
s=s.replace('if(i.hasExtra("storage_report")&&storageReport!=null)storageReport.setText(i.getStringExtra("storage_report"));','if(i.hasExtra("storage_report")&&storageReport!=null)storageReport.setText(i.getStringExtra("storage_report"));if(i.hasExtra("hourly_report")&&hourlyReport!=null)hourlyReport.setText(i.getStringExtra("hourly_report"));')
p.write_text(s)
PY
cat > app/src/main/java/com/suhas/nsedeliverymomentum/HourlyAdaptiveLearning.java <<'JAVA'
package com.suhas.nsedeliverymomentum;
import java.time.*;import java.util.Locale;
final class HourlyAdaptiveLearning {
 static final int TARGET_HITS_PER_HOUR=5;static final double MAX_RATE=3.0;
 static final class State{final int hits,resolved,calls,deficit;final double rate;final long deepIntervalMs;final int poolBoost;final boolean acceleratedConfirmation;State(int h,int r,int c,int d,double lr,long interval,int boost,boolean fast){hits=h;resolved=r;calls=c;deficit=d;rate=lr;deepIntervalMs=interval;poolBoost=boost;acceleratedConfirmation=fast;}String summary(){return String.format(Locale.US,"HOURLY %d/5 wins • calls %d • learning %.2fx%s",hits,calls,rate,acceleratedConfirmation?" • FAST CONFIRM":"");}}
 private final LearningStore learning;private final SecretStore store;HourlyAdaptiveLearning(LearningStore l,SecretStore s){learning=l;store=s;}
 State state(){int hits=learning.hitsCurrentHour(),resolved=learning.resolvedCurrentHour(),calls=learning.callsCurrentHour(),deficit=Math.max(0,5-hits),minute=ZonedDateTime.now(ZoneId.of("Asia/Kolkata")).getMinute();double rate=1.0+deficit*0.30;if(minute>=30&&hits<3)rate+=0.25;if(minute>=45&&hits<5)rate+=0.25;rate=Math.max(1.0,Math.min(MAX_RATE,rate));long interval=(long)Math.max(45000,90000.0/rate);int boost=(int)Math.round(20*(rate-1));boolean fast=rate>=2.0;State st=new State(hits,resolved,calls,deficit,rate,interval,boost,fast);store.put("hourly_learning_summary",st.summary()+" • quality floors protected");store.put("hourly_learning_rate",String.format(Locale.US,"%.2f",rate));return st;}
 static String storedSummary(SecretStore s){return s.get("hourly_learning_summary","HOURLY 0/5 wins • learning 1.00x • quality floors protected");}
}
JAVA
cat > app/src/test/java/com/suhas/nsedeliverymomentum/HourlyAdaptiveLearningTest.java <<'JAVA'
package com.suhas.nsedeliverymomentum;import org.junit.Test;import static org.junit.Assert.*;public class HourlyAdaptiveLearningTest{@Test public void targetIsFive(){assertEquals(5,HourlyAdaptiveLearning.TARGET_HITS_PER_HOUR);}@Test public void maxRateIsThree(){assertEquals(3.0,HourlyAdaptiveLearning.MAX_RATE,0.0001);}}
JAVA
cat > RELEASE-NOTES-v1.9.0.txt <<'TXT'
NSE INTRADAY MOMENTUM v1.9.0 — HOURLY ADAPTIVE LEARNING

Hourly objective: 5 resolved successful calls per market hour. This is a target, not a guarantee.
When behind target, learning/search intensity increases automatically up to 3.0x.
Deep scans accelerate toward a protected 45-second minimum and candidate pools broaden.
At >=2x learning intensity, confirmation can accelerate from 3 scans to 2, but score-quality floors remain unchanged.
Signals unresolved after 60 minutes are graded as misses for hourly learning.
LONG + LONG + SHORT engines, ENTRY→TARGET alerts, NIGHT LAB and bounded housekeeping remain.
No weak call is forced merely to fill an hourly quota.
TXT
cd ..
mv nse-intraday-v180 nse-intraday-v190
