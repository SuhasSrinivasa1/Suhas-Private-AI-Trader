package com.suhas.research360engine;

import android.content.Context;
import android.content.SharedPreferences;

public final class AppState {
    private static final String PREF = "r360_state";
    private static final String K_ARMED = "armed", K_LIVE = "live_orders", K_BUDGET = "budget", K_DAILY_LIMIT = "daily_loss_limit";
    private static final String K_CAPTURE_PKG = "capture_package", K_EXPECTED_IP = "expected_static_ip", K_PUBLIC_IP = "last_public_ip", K_IP_VERIFIED_AT = "ip_verified_at";
    private static final String K_LAST_EOD_SCAN = "last_eod_scan", K_LAST_PRE_SCAN = "last_pre_scan", K_LAST_ACTIVATION = "last_activation";
    private static final String K_LAST_SECTOR_SCAN = "last_sector_scan", K_SECTOR_SUMMARY = "sector_summary", K_SECTOR_NAME = "sector_name", K_SECTOR_PCT = "sector_pct";
    private static final String K_API_HEALTH_AT = "api_health_at", K_API_AUTH_AT = "api_auth_at", K_API_HEALTH_OK = "api_health_ok", K_API_HEALTH_MSG = "api_health_msg", K_API_UCC = "api_ucc_masked", K_API_FAILURES = "api_failures";
    private static final String K_V14_MIGRATED = "v14_migrated", K_RAW_BASELINE = "raw_callback_baseline";

    private AppState() {}
    private static SharedPreferences p(Context c){ return c.getSharedPreferences(PREF,Context.MODE_PRIVATE); }

    public static void migrateV14(Context c,long rawCallbackCount){
        if(p(c).getBoolean(K_V14_MIGRATED,false))return;
        p(c).edit().putBoolean(K_V14_MIGRATED,true).putFloat(K_DAILY_LIMIT,500f).putLong(K_RAW_BASELINE,Math.max(0,rawCallbackCount)).apply();
    }
    public static long rawBaseline(Context c){ return p(c).getLong(K_RAW_BASELINE,0); }

    public static boolean isArmed(Context c){return p(c).getBoolean(K_ARMED,true);} public static void setArmed(Context c,boolean v){p(c).edit().putBoolean(K_ARMED,v).apply();}
    public static boolean liveOrders(Context c){return p(c).getBoolean(K_LIVE,false);} public static void setLiveOrders(Context c,boolean v){p(c).edit().putBoolean(K_LIVE,v).apply();}
    public static double budget(Context c){return Math.max(1,p(c).getFloat(K_BUDGET,10000f));} public static void setBudget(Context c,double v){p(c).edit().putFloat(K_BUDGET,(float)Math.max(1,v)).apply();}
    public static double dailyLossLimit(Context c){return Math.max(1,p(c).getFloat(K_DAILY_LIMIT,500f));} public static void setDailyLossLimit(Context c,double v){p(c).edit().putFloat(K_DAILY_LIMIT,(float)Math.max(1,v)).apply();}

    public static String capturePackage(Context c){return p(c).getString(K_CAPTURE_PKG,"");} public static void setCapturePackage(Context c,String v){p(c).edit().putString(K_CAPTURE_PKG,v==null?"":v).apply();}
    public static String expectedStaticIp(Context c){return p(c).getString(K_EXPECTED_IP,"").trim();}
    public static void setExpectedStaticIp(Context c,String v){p(c).edit().putString(K_EXPECTED_IP,v==null?"":v.trim()).putLong(K_IP_VERIFIED_AT,0).apply();}
    public static String lastPublicIp(Context c){return p(c).getString(K_PUBLIC_IP,"").trim();} public static long ipVerifiedAt(Context c){return p(c).getLong(K_IP_VERIFIED_AT,0);}
    public static void setIpCheck(Context c,String publicIp,boolean verified){p(c).edit().putString(K_PUBLIC_IP,publicIp==null?"":publicIp.trim()).putLong(K_IP_VERIFIED_AT,verified?System.currentTimeMillis():0).apply();}

    public static String lastEodScan(Context c){return p(c).getString(K_LAST_EOD_SCAN,"");} public static void setLastEodScan(Context c,String d){p(c).edit().putString(K_LAST_EOD_SCAN,d==null?"":d).apply();}
    public static String lastPreScan(Context c){return p(c).getString(K_LAST_PRE_SCAN,"");} public static void setLastPreScan(Context c,String d){p(c).edit().putString(K_LAST_PRE_SCAN,d==null?"":d).apply();}
    public static String lastActivation(Context c){return p(c).getString(K_LAST_ACTIVATION,"");} public static void setLastActivation(Context c,String d){p(c).edit().putString(K_LAST_ACTIVATION,d==null?"":d).apply();}
    public static String lastSectorScan(Context c){return p(c).getString(K_LAST_SECTOR_SCAN,"");} public static void setLastSectorScan(Context c,String d){p(c).edit().putString(K_LAST_SECTOR_SCAN,d==null?"":d).apply();}
    public static String sectorSummary(Context c){return p(c).getString(K_SECTOR_SUMMARY,"Waiting for Groww trending-sector confirmation after market open…");}
    public static String sectorName(Context c){return p(c).getString(K_SECTOR_NAME,"");} public static double sectorPct(Context c){return p(c).getFloat(K_SECTOR_PCT,0f);}
    public static void setSectorState(Context c,String name,double pct,String summary){p(c).edit().putString(K_SECTOR_NAME,name==null?"":name).putFloat(K_SECTOR_PCT,(float)pct).putString(K_SECTOR_SUMMARY,summary==null?"":summary).apply();}

    public static long apiHealthAt(Context c){return p(c).getLong(K_API_HEALTH_AT,0);} public static long apiAuthAt(Context c){return p(c).getLong(K_API_AUTH_AT,0);} public static boolean apiHealthOk(Context c){return p(c).getBoolean(K_API_HEALTH_OK,false);}
    public static String apiHealthMessage(Context c){return p(c).getString(K_API_HEALTH_MSG,"Not validated yet");} public static String apiUccMasked(Context c){return p(c).getString(K_API_UCC,"");} public static int apiFailures(Context c){return p(c).getInt(K_API_FAILURES,0);}
    public static boolean apiHealthyFresh(Context c,long maxAgeMs){return apiHealthOk(c)&&System.currentTimeMillis()-apiHealthAt(c)<=maxAgeMs;}
    public static void setApiAuthAt(Context c,long when){p(c).edit().putLong(K_API_AUTH_AT,when).apply();}
    public static void setApiHealth(Context c,boolean ok,String msg,String ucc){SharedPreferences.Editor e=p(c).edit().putLong(K_API_HEALTH_AT,System.currentTimeMillis()).putBoolean(K_API_HEALTH_OK,ok).putString(K_API_HEALTH_MSG,msg==null?"":msg);if(ucc!=null&&!ucc.isEmpty())e.putString(K_API_UCC,maskUcc(ucc));e.putInt(K_API_FAILURES,ok?0:Math.min(99,apiFailures(c)+1)).apply();}

    public static boolean markNotificationIfNew(Context c,String fingerprint,long windowMs){if(fingerprint==null||fingerprint.isEmpty())return true;String k="nf_"+fingerprint;long now=System.currentTimeMillis(),last=p(c).getLong(k,0);if(now-last<windowMs)return false;p(c).edit().putLong(k,now).apply();return true;}
    public static boolean buyNotified(Context c,long signalId){return p(c).getBoolean("buy_notified_"+signalId,false);} public static void setBuyNotified(Context c,long signalId){p(c).edit().putBoolean("buy_notified_"+signalId,true).apply();}
    public static String tradeGtt(Context c,long tradeId){return p(c).getString("gtt_"+tradeId,"");} public static void setTradeGtt(Context c,long tradeId,String id){p(c).edit().putString("gtt_"+tradeId,id==null?"":id).apply();} public static void clearTradeGtt(Context c,long tradeId){p(c).edit().remove("gtt_"+tradeId).apply();}

    private static String maskUcc(String u){if(u==null||u.isEmpty())return"";u=u.trim();return u.length()<=4?"••••"+u:"••••"+u.substring(u.length()-4);}
}
