from pathlib import Path
import re

root=Path('/tmp/r360')

# ---------- version ----------
p=root/'app/build.gradle'
s=p.read_text()
s=re.sub(r"versionCode\s+\d+","versionCode 170",s,count=1)
s=re.sub(r"versionName\s+'[^']+'","versionName '1.7.0'",s,count=1)
p.write_text(s)

# ---------- LearningBackup: fix sector_meta fingerprint + throttle future failures ----------
p=root/'app/src/main/java/com/suhas/research360engine/LearningBackup.java'
s=p.read_text()
s=s.replace('private static final String K_RESTORE="last_restore_at";',
            'private static final String K_RESTORE="last_restore_at";\n    private static final String K_LAST_FAIL="last_backup_fail_at";',1)
s=s.replace('private static final long CHECKPOINT_MS=15L*60L*1000L;',
            'private static final long CHECKPOINT_MS=15L*60L*1000L;\n    private static final long FAIL_BACKOFF_MS=5L*60L*1000L;',1)
# backup metadata version
s=s.replace('root.put("backup_format",1);root.put("app_version","1.6.0");',
            'root.put("backup_format",1);root.put("app_version","1.7.0");',1)
# clear failure backoff on success
s=s.replace('.putString(K_LAST_REASON,reason).putString(K_LAST_FP,fp).apply();',
            '.putString(K_LAST_REASON,reason).putString(K_LAST_FP,fp).remove(K_LAST_FAIL).apply();',1)
# robust fingerprint: sector_meta has signal_id rather than id
pattern=r'    private static String fingerprint\(Context c\)\{.*?return b\.toString\(\);\}'
replacement='''    private static String fingerprint(Context c){\n        SQLiteDatabase db=Db.get(c).getReadableDatabase();StringBuilder b=new StringBuilder();\n        for(String t:new String[]{"signals","snapshots","trades","predictions","sector_meta","logs"}){\n            if(!tableExists(db,t))continue;Set<String> cs=columns(db,t);String key=cs.contains("id")?"id":(cs.contains("signal_id")?"signal_id":null);\n            b.append(t).append(':');if(key!=null)b.append(scalar(db,"SELECT COALESCE(MAX("+key+"),0) FROM "+t));else b.append('0');b.append('/').append(scalar(db,"SELECT COUNT(*) FROM "+t)).append(';');\n        }return b.toString();\n    }'''
s2,n=re.subn(pattern,replacement,s,count=1,flags=re.S)
if n!=1: raise SystemExit('LearningBackup fingerprint marker not found')
s=s2
# backoff repeated failures so RECENT ENGINE LOG cannot be flooded
old='''    public static void maybeBackup(Context c){\n        synchronized(LOCK){\n            try{\n                if(!storageReady(c))return;'''
new='''    public static void maybeBackup(Context c){\n        synchronized(LOCK){\n            try{\n                if(!storageReady(c))return;\n                SharedPreferences bp=c.getSharedPreferences(PREF,Context.MODE_PRIVATE);long now0=System.currentTimeMillis();if(now0-bp.getLong(K_LAST_FAIL,0)<FAIL_BACKOFF_MS)return;'''
if old not in s: raise SystemExit('maybeBackup start marker missing')
s=s.replace(old,new,1)
s=s.replace('''            }catch(Exception e){try{Db.get(c).log("BACKUP","Automatic backup failed: "+shortMsg(e));}catch(Exception ignored){}}''',
            '''            }catch(Exception e){try{c.getSharedPreferences(PREF,Context.MODE_PRIVATE).edit().putLong(K_LAST_FAIL,System.currentTimeMillis()).apply();Db.get(c).log("BACKUP","Automatic backup failed: "+shortMsg(e));}catch(Exception ignored){}}''',1)
p.write_text(s)

# ---------- MainActivity: clearer UI and responsive recommendation buttons ----------
p=root/'app/src/main/java/com/suhas/research360engine/MainActivity.java'
s=p.read_text()
# Version labels / copy
s=re.sub(r'v1\.6 • LG G7 ThinQ •[^"\n]*',
         'v1.7 • LG G7 ThinQ • persistent learning • responsive manual BUY/recheck • positive-sector scanner',s,count=1)
s=s.replace('v1.5 ignores generic Research360 app notifications','v1.7 ignores generic Research360 app notifications')
s=s.replace('v1.5 rechecks the score, Groww API and exact static IP.','v1.7 rechecks the score, Groww API and exact static IP.')
s=s.replace('v1.5 re-verifies the actual public egress IP','v1.7 re-verifies the actual public egress IP')
s=s.replace('Before sending, v1.4 rechecks the score, Groww API and exact static IP.','Before sending, v1.7 rechecks the score, Groww API and exact static IP.')
s=s.replace('Default daily loss ceiling is ₹500 in v1.4.','Default daily loss ceiling is ₹500.')
# More useful section names
s=s.replace('TODAY — TOP 5 FROM RESEARCH360','RESEARCH360 PICKS — TODAY TOP 5')
s=s.replace('NEXT SESSION — OWN MODEL TOP 5','OWN MODEL — NEXT SESSION TOP 5')
s=s.replace('POSITIVE SECTORS — GLOBAL TOP 5','POSITIVE SECTORS — BEST 5 STOCKS')
# Risk fields need visible labels even after text is entered
old='''LinearLayout risk=card(root);risk.addView(text("CAPITAL & RISK",13,MUTED,true));budget=numberField("Budget ₹",String.format(Locale.US,"%.0f",AppState.budget(this)));risk.addView(budget);limit=numberField("Daily loss limit ₹",String.format(Locale.US,"%.0f",AppState.dailyLossLimit(this)));risk.addView(limit);'''
new='''LinearLayout risk=card(root);risk.addView(text("CAPITAL & RISK",13,MUTED,true));risk.addView(text("Trade budget (₹)",10,MUTED,true));budget=numberField("Budget ₹",String.format(Locale.US,"%.0f",AppState.budget(this)));risk.addView(budget);risk.addView(text("Daily loss ceiling (₹)",10,MUTED,true));limit=numberField("Daily loss limit ₹",String.format(Locale.US,"%.0f",AppState.dailyLossLimit(this)));risk.addView(limit);'''
if old in s:s=s.replace(old,new,1)
# Reduce log wall; diagnostics remain available in backup ZIP
s=s.replace('recentLogs(20)','recentLogs(8)',1)
s=s.replace('RECENT ENGINE LOG','RECENT ENGINE LOG — LAST 8',1)
# Own-model rows get breathing room
s=s.replace("for(Db.Prediction p:x)b.append(p.line()).append('\\n');","for(Db.Prediction p:x)b.append(p.line()).append(\"\\n\\n\");",1)

# Replace recommendation rendering. Closed/stale rows now say RECHECK and respond instead of looking like broken BUY buttons.
pattern=r'    private void renderRecommendations\(LinearLayout box,List<Db\.Recommendation> rows,String empty\)\{.*?\n    \}\n    private boolean isBuyableStatus\(String s\)\{.*?\}\n'
replacement='''    private void renderRecommendations(LinearLayout box,List<Db.Recommendation> rows,String empty){\n        box.removeAllViews();if(rows==null||rows.isEmpty()){box.addView(text(empty,11,MUTED,false));return;}int rank=1;\n        for(Db.Recommendation r:rows){\n            LinearLayout line=new LinearLayout(this);line.setOrientation(LinearLayout.HORIZONTAL);line.setPadding(0,dp(8),0,dp(8));\n            LinearLayout left=new LinearLayout(this);left.setOrientation(LinearLayout.VERTICAL);\n            String sector=(r.sector==null||r.sector.isEmpty())?"":(" • "+r.sector);\n            TextView name=text((rank++)+". "+r.symbol,14,Color.WHITE,true);left.addView(name);\n            TextView detail=text(String.format(Locale.US,"%.0f%% • %s%s • %s",r.score,pretty(r.category),sector,r.status),10,statusColor(r.status),false);left.addView(detail);\n            LinearLayout.LayoutParams lp=new LinearLayout.LayoutParams(0,-2,1);line.addView(left,lp);\n            String label=actionLabel(r.status);Button b=smallButton(label);boolean active=!isLiveActive(r.status);b.setEnabled(active);b.setAlpha(active?1.0f:0.45f);\n            if(active)b.setOnClickListener(v->openBuyDialog(r.id));line.addView(b,new LinearLayout.LayoutParams(dp(92),dp(46)));box.addView(line);\n        }\n    }\n    private static boolean isLiveActive(String s){return s!=null&&s.contains("LIVE_ACTIVE");}\n    private String actionLabel(String s){if(isLiveActive(s))return"ACTIVE";if(s==null)return"RECHECK";String x=s.toUpperCase(Locale.ROOT);if(x.contains("NEW")||x.contains("WATCH")||x.contains("SHADOW_ACTIVE"))return"BUY";return"RECHECK";}\n    private int statusColor(String s){if(s==null)return MUTED;String x=s.toUpperCase(Locale.ROOT);if(x.contains("LIVE_ACTIVE"))return GREEN;if(x.contains("NEW")||x.contains("WATCH")||x.contains("SHADOW_ACTIVE"))return ACCENT;if(x.contains("REJECT")||x.contains("EXPIRED"))return AMBER;return MUTED;}\n'''
s2,n=re.subn(pattern,replacement,s,count=1,flags=re.S)
if n!=1: raise SystemExit('renderRecommendations replacement failed')
s=s2

# Manual button response: always explain what is happening. Recheck stale/closed candidates using current Groww data, but never send outside market hours.
pattern=r'    private void openBuyDialog\(long signalId\)\{\n        Db\.Signal s=Db\.get\(this\)\.getSignal\(signalId\);.*?\n    \}\n    private void showAmountDialog'
replacement='''    private void openBuyDialog(long signalId){\n        Db.Signal s=Db.get(this).getSignal(signalId);if(s==null){dialog("Recommendation unavailable","This recommendation no longer exists in the local learning database.");return;}\n        if(!marketOpen()){dialog("Market closed — no order sent",s.symbol+" can be rechecked during the NSE cash session. The button is working; v1.7 deliberately refuses to submit a manual BUY outside the live-market window.");return;}\n        Toast.makeText(this,"Rechecking "+s.symbol+" with live Groww data…",Toast.LENGTH_SHORT).show();\n        new Thread(()->{try{\n            GrowwClient gw=new GrowwClient(this);GrowwClient.Health h=gw.validate(false);if(!h.ok)throw new IllegalStateException("Groww API not healthy: "+h.message);\n            Db.MarketSnapshot q=gw.getQuote(s.symbol);StrategyEngine se=new StrategyEngine(this);double score=se.score(s,q);double threshold=se.qualifyThreshold(s);boolean entryOk=se.entryNearEnough(s,q.ltp);\n            if(score<threshold||!entryOk){String why=String.format(Locale.US,"Current score %.0f%% (required %.0f%%) • LTP ₹%.2f • original entry ₹%.2f. %s",score,threshold,q.ltp,s.entry,entryOk?"Score is below the current gate.":"Price is outside the validated entry window.");runOnUiThread(()->dialog("Not buyable right now",why));return;}\n            runOnUiThread(()->showAmountDialog(s,q,score));\n        }catch(Exception e){runOnUiThread(()->dialog("BUY recheck failed",shortMsg(e)));}}).start();\n    }\n    private void showAmountDialog'''
s2,n=re.subn(pattern,replacement,s,count=1,flags=re.S)
if n!=1: raise SystemExit('openBuyDialog replacement failed')
s=s2
# Final belt-and-braces market-open guard before any REAL order
old='''try{Db.Signal s=Db.get(this).getSignal(signalId);if(s==null)throw new IllegalStateException("Signal missing");Db.Stats st=Db.get(this).stats();'''
new='''try{if(!marketOpen())throw new IllegalStateException("Market is closed; no order sent");Db.Signal s=Db.get(this).getSignal(signalId);if(s==null)throw new IllegalStateException("Signal missing");Db.Stats st=Db.get(this).stats();'''
if old not in s: raise SystemExit('executeManualBuy marker missing')
s=s.replace(old,new,1)
# Slightly calmer cards and buttons; touch target retained
s=s.replace('x.setPadding(dp(14),dp(12),dp(14),dp(12));','x.setPadding(dp(14),dp(14),dp(14),dp(14));',1)
s=s.replace('d.setCornerRadius(dp(14));','d.setCornerRadius(dp(16));',1)
s=s.replace('d.setColor(Color.rgb(44,91,172));d.setCornerRadius(dp(10));','d.setColor(Color.rgb(35,110,210));d.setCornerRadius(dp(12));',1)
p.write_text(s)

# ---------- static contract ----------
checks=[
    (root/'app/build.gradle',"versionName '1.7.0'"),
    (root/'app/src/main/java/com/suhas/research360engine/LearningBackup.java','cs.contains("signal_id")'),
    (root/'app/src/main/java/com/suhas/research360engine/LearningBackup.java','FAIL_BACKOFF_MS'),
    (root/'app/src/main/java/com/suhas/research360engine/MainActivity.java','Market closed — no order sent'),
    (root/'app/src/main/java/com/suhas/research360engine/MainActivity.java','actionLabel'),
    (root/'app/src/main/java/com/suhas/research360engine/MainActivity.java','RESEARCH360 PICKS — TODAY TOP 5'),
    (root/'app/src/main/java/com/suhas/research360engine/MainActivity.java','RECENT ENGINE LOG — LAST 8'),
]
for f,t in checks:
    if t not in f.read_text():raise SystemExit(f'missing {t} in {f}')
print('v1.7 patch applied')
