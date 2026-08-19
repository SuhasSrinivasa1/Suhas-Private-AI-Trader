package com.suhas.research360engine;

import android.content.Context;

import java.time.LocalTime;
import java.time.ZoneId;
import java.util.Locale;

/** Deterministic risk/score/exit engine. Research360 target/SL are deliberately not used. */
public final class StrategyEngine {
    public static final double MIN_NET_PROFIT = 100.0;
    private static final ZoneId IST = ZoneId.of("Asia/Kolkata");
    private final Context context;
    private final Db db;

    public StrategyEngine(Context c) { context=c.getApplicationContext(); db=Db.get(c); }

    public String product(Db.Signal s) { return "MOST_OVERNIGHT".equals(s.category) ? "CNC" : "MIS"; }

    public int quantityFor(double price) { return quantityForAmount(AppState.budget(context),price); }
    public int quantityForAmount(double amount,double price){if(price<=0||amount<=0)return 0;return (int)Math.floor(amount/price);}

    public double score(Db.Signal s, Db.MarketSnapshot q) {
        double x=50;
        if("QUANT_INTRADAY".equals(s.category)) x+=3;
        if("MOST_INTRADAY_CASH".equals(s.category)) x+=1;
        if("MOST_OVERNIGHT".equals(s.category)) x-=2;
        if("OWN_MODEL_INTRADAY".equals(s.category)) x+=4;
        if("SECTOR_MOMENTUM_INTRADAY".equals(s.category)) x+=2;

        // Real order-book pressure: strongly positive is useful, extreme values are capped.
        x += clamp(q.depthImbalance,-0.65,0.65)*18.0;
        if(q.spreadBps>0){ if(q.spreadBps<=4)x+=5; else if(q.spreadBps<=10)x+=2; else if(q.spreadBps>25)x-=10; else x-=4; }
        if(q.averagePrice>0 && q.ltp>0){ double above=(q.ltp/q.averagePrice-1)*100.0; if(above>=0&&above<=1.1)x+=8; else if(above>2.2)x-=9; else if(above<-.4)x-=8; }
        if(q.dayChangePct>=0.15&&q.dayChangePct<=2.25)x+=7; else if(q.dayChangePct>4.0)x-=11; else if(q.dayChangePct<-.75)x-=8;
        if(q.rangePosition>=.48&&q.rangePosition<=.86)x+=6; else if(q.rangePosition>.96)x-=9; else if(q.rangePosition<.25)x-=5;

        // Late-call detector: do not blindly chase a signal that arrived after the move.
        double ref=s.entry>0?s.entry:s.firstLtp;
        if(ref>0&&q.ltp>0){ double extension=(q.ltp/ref-1)*100.0; if(extension>=-.10&&extension<=.18)x+=6; else if(extension>.75)x-=14; else if(extension>.35)x-=8; }
        if(s.closeSeen)x-=5; // close call is evidence, never an automatic exit.

        // Outcomes adapt the category threshold/score, while preventing tiny samples from dominating.
        Db.CategoryStats cs=db.categoryStats(s.category);
        if(cs.trades>=8){ double edge=(cs.winRate()-.55)*20.0 + clamp(cs.avgNet/100.0,-1,1)*3.0; x += clamp(edge,-8,8); }
        // Scanner-origin scores are priors, not certainty. Blend rather than overwrite them.
        if(("OWN_MODEL_INTRADAY".equals(s.category)||"SECTOR_MOMENTUM_INTRADAY".equals(s.category))&&s.score>0)x=.55*s.score+.45*x;
        return clamp(x,0,96);
    }

    public double qualifyThreshold(Db.Signal s) {
        double t="SECTOR_MOMENTUM_INTRADAY".equals(s.category)?74:("OWN_MODEL_INTRADAY".equals(s.category)?78:76);
        Db.CategoryStats cs=db.categoryStats(s.category);
        if(cs.trades>=8){ if(cs.winRate()>=.68&&cs.avgNet>50)t-=3; if(cs.winRate()<.45||cs.avgNet<0)t+=5; }
        return clamp(t,70,86);
    }

    public boolean entryNearEnough(Db.Signal s,double ltp) {
        if(ltp<=0)return false;
        if(s.entry<=0) return true; // unknown entry: first observed market price becomes paper reference only.
        double d=(ltp/s.entry-1)*100.0;
        return d>=-.10 && d<=.35;
    }

    public boolean triggerReached(Db.Signal s,double ltp) { return s.entry<=0 || ltp>=s.entry; }

    public double requiredNet100MovePct(double entry,int qty,String product){
        if(entry<=0||qty<=0)return 999; double lo=entry,hi=entry*1.06;
        for(int i=0;i<35;i++){double mid=(lo+hi)/2;double n=netPnl(entry,mid,qty,product);if(n>=MIN_NET_PROFIT)hi=mid;else lo=mid;}
        return (hi/entry-1)*100.0;
    }

    public double realisticTarget(double entry,int qty,String product,double score,Db.MarketSnapshot q){
        if(entry<=0||qty<=0)return 0;double required=requiredNet100MovePct(entry,qty,product);
        double momentum=.45;if(q!=null){momentum=.35+Math.max(0,Math.min(1.15,q.dayChangePct*.16))+Math.max(0,q.depthImbalance)*.35;if(q.rangePosition>.92)momentum-=.18;}
        double scoreBoost=Math.max(0,score-72)*.018;double pct=Math.max(required+.10,momentum+scoreBoost);
        double cap="CNC".equals(product)?3.0:2.25;pct=clamp(pct,required+.08,cap);return Math.round(entry*(1+pct/100.0)*20.0)/20.0;
    }

    public boolean economicallyFeasible(double entry,int qty,String product,double score){
        double req=requiredNet100MovePct(entry,qty,product);
        double cap="CNC".equals(product)?3.0:2.25;
        if(score>=88)cap+=.45;
        return req<=cap;
    }

    public ExitDecision exitDecision(Db.Signal s,Db.Trade t,Db.MarketSnapshot q,double currentScore){
        ExitDecision d=new ExitDecision(); String product=product(s); d.net=netPnl(t.entry,q.ltp,t.qty,product);
        d.peakNet=netPnl(t.entry,Math.max(t.peak,q.ltp),t.qty,product);
        long age=System.currentTimeMillis()-t.entryTs;
        double dailyLimit=AppState.dailyLossLimit(context);
        double perTradeHard=Math.min(Math.max(45.0,AppState.budget(context)*0.0075),Math.max(45.0,dailyLimit*.60));

        if(d.net<=-perTradeHard){d.exit=true;d.reason="HARD_RISK_CAP";return d;}
        if("MIS".equals(product)&&LocalTime.now(IST).isAfter(LocalTime.of(15,14))){d.exit=true;d.reason="INTRADAY_TIME_EXIT";return d;}

        // Once >= ₹100 net is available, lock at least ₹100 and trail the runner.
        if(d.peakNet>=MIN_NET_PROFIT){
            double giveback=clamp(d.peakNet*.25,35,Math.max(75,d.peakNet*.32));
            double floor=Math.max(MIN_NET_PROFIT,d.peakNet-giveback);
            // Anticipate some slippage by adding a small reserve to the trigger floor.
            double trigger=floor+Math.min(20,Math.max(5,t.entry*t.qty*0.00025));
            d.protectedFloor=floor;
            if(d.net<=trigger){d.exit=true;d.reason="DYNAMIC_PROFIT_TRAIL";return d;}
            if(currentScore<48&&d.net>=MIN_NET_PROFIT){d.exit=true;d.reason="MOMENTUM_PROTECT";return d;}
        } else {
            // A weak/non-performing signal is not allowed to consume the whole risk budget.
            if(age>8L*60L*1000L && d.net<25){d.exit=true;d.reason="STAGNANT_TIME_EXIT";return d;}
            if(age>2L*60L*1000L && currentScore<42 && d.net>-35){d.exit=true;d.reason="FAILED_MOMENTUM";return d;}
            if(s.closeSeen&&currentScore<50&&d.net>0){d.exit=true;d.reason="R360_CLOSE_CONFIRMED_BY_OUR_MODEL";return d;}
        }
        return d;
    }

    public static double netPnl(double buy,double sell,int qty,String product){ return (sell-buy)*qty - charges(buy,sell,qty,product); }

    public static double charges(double buy,double sell,int qty,String product){
        if(qty<=0||buy<=0||sell<=0)return 0; double bv=buy*qty,sv=sell*qty;
        double broker=brokerage(bv)+brokerage(sv);
        double exch=(bv+sv)*0.0000297, sebi=(bv+sv)*0.000001, ipft=(bv+sv)*0.000001;
        double stt,stamp,dp=0;
        if("CNC".equals(product)){stt=(bv+sv)*0.001;stamp=bv*0.00015;dp=20.0;} else {stt=sv*0.00025;stamp=bv*0.00003;}
        double gst=.18*(broker+exch+sebi+ipft+dp);
        return broker+exch+sebi+ipft+stt+stamp+dp+gst;
    }

    private static double brokerage(double v){ if(v<=0)return 0; double x=v*.001; if(x<5)return Math.min(5,v*.025); return Math.min(20,x); }
    private static double clamp(double x,double a,double b){return Math.max(a,Math.min(b,x));}
    public static final class ExitDecision { public boolean exit; public String reason=""; public double net,peakNet,protectedFloor; }
}
