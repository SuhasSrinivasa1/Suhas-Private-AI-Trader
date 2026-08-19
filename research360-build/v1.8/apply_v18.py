from pathlib import Path
import re

root=Path('/tmp/r360')

# ---------- version ----------
p=root/'app/build.gradle'
s=p.read_text()
s=re.sub(r"versionCode\s+\d+","versionCode 180",s,count=1)
s=re.sub(r"versionName\s+'[^']+'","versionName '1.8.0'",s,count=1)
p.write_text(s)

# ---------- Db: Research360-only active pipeline ----------
p=root/'app/src/main/java/com/suhas/research360engine/Db.java'
s=p.read_text()
# Old own-model/sector signals stay in history/backup, but never participate again.
s=s.replace("WHERE action='BUY' AND status IN ('NEW','WATCH','SHADOW_ACTIVE','LIVE_ACTIVE') ORDER BY last_update ASC LIMIT 250",
            "WHERE action='BUY' AND category NOT IN ('OWN_MODEL_INTRADAY','SECTOR_MOMENTUM_INTRADAY') AND status IN ('NEW','WATCH','SHADOW_ACTIVE','LIVE_ACTIVE') ORDER BY last_update ASC LIMIT 250",1)
# Add one-time retirement + actionable-only query.
marker='    public Signal getSignal(long id){'
insert='''    public void disableRemovedEngines(){\n        SQLiteDatabase db=getWritableDatabase();long now=System.currentTimeMillis();ContentValues sv=new ContentValues();sv.put("status","DISABLED_V18");sv.put("last_update",now);db.update("signals",sv,"category IN ('OWN_MODEL_INTRADAY','SECTOR_MOMENTUM_INTRADAY') AND status IN ('NEW','WATCH','SHADOW_ACTIVE')",null);ContentValues tv=new ContentValues();tv.put("status","CLOSED");tv.put("exit_ts",now);tv.put("exit_reason","ENGINE_REMOVED_V18");db.update("trades",tv,"mode='SHADOW' AND category IN ('OWN_MODEL_INTRADAY','SECTOR_MOMENTUM_INTRADAY') AND status='OPEN'",null);\n    }\n\n    public List<Recommendation> actionableR360Now(){long start=LocalDate.now(IST).atStartOfDay(IST).toInstant().toEpochMilli();ArrayList<Recommendation> out=new ArrayList<>();Set<String> seen=new HashSet<>();Cursor c=getReadableDatabase().rawQuery("SELECT id,symbol,category,score,status,entry,mfe,mae,ts FROM signals WHERE action='BUY' AND ts>=? AND category NOT IN ('OWN_MODEL_INTRADAY','SECTOR_MOMENTUM_INTRADAY') AND status IN ('SHADOW_ACTIVE','LIVE_ACTIVE') AND symbol!='' ORDER BY CASE WHEN status='LIVE_ACTIVE' THEN 0 ELSE 1 END,score DESC,last_update DESC",new String[]{String.valueOf(start)});try{while(c.moveToNext()&&out.size()<3){String sym=c.getString(1);if(!seen.add(sym))continue;Recommendation r=new Recommendation();r.id=c.getLong(0);r.symbol=sym;r.category=c.getString(2);r.score=c.getDouble(3);r.status=c.getString(4);r.entry=c.getDouble(5);r.mfe=c.getDouble(6);r.mae=c.getDouble(7);out.add(r);}}finally{c.close();}return out;}\n\n    public String r360TodayPipeline(){long start=LocalDate.now(IST).atStartOfDay(IST).toInstant().toEpochMilli();Cursor c=getReadableDatabase().rawQuery("SELECT COUNT(*),COALESCE(SUM(CASE WHEN status='WATCH' THEN 1 ELSE 0 END),0),COALESCE(SUM(CASE WHEN status IN ('REJECTED','EXPIRED') THEN 1 ELSE 0 END),0),COALESCE(SUM(CASE WHEN status IN ('SHADOW_ACTIVE','LIVE_ACTIVE') THEN 1 ELSE 0 END),0) FROM signals WHERE action='BUY' AND ts>=? AND category NOT IN ('OWN_MODEL_INTRADAY','SECTOR_MOMENTUM_INTRADAY')",new String[]{String.valueOf(start)});try{if(c.moveToFirst())return String.format(Locale.US,"Today: %d analysed • %d internal watch • %d rejected/expired • %d actionable",c.getLong(0),c.getLong(1),c.getLong(2),c.getLong(3));}finally{c.close();}return "Today: waiting for Research360 calls";}\n\n'''
if marker not in s: raise SystemExit('Db insertion marker missing')
s=s.replace(marker,insert+marker,1)
# Evidence maturity and live gate now depend on resolved Research360 shadow outcomes, not callback counts.
s=s.replace('public int r360Maturity(){return maturity(resolvedSignals+r360ShadowTrades*2,40);}',
            'public int r360Maturity(){return maturity(r360ShadowTrades,100);}',1)
s=s.replace('public boolean r360GateReady(){return r360Confidence()>=80&&r360ShadowTrades>=14&&r360ShadowNet>0&&r360WinRate()>=.58;}',
            'public boolean r360GateReady(){return r360Confidence()>=80&&r360ShadowTrades>=50&&r360ShadowNet>0&&r360WinRate()>=.60;}',1)
s=s.replace('public boolean anyLiveGateReady(){return r360GateReady()||ownGateReady()||sectorGateReady();}',
            'public boolean anyLiveGateReady(){return r360GateReady();}',1)
p.write_text(s)

# ---------- StrategyEngine: only Research360 categories + stricter qualification ----------
p=root/'app/src/main/java/com/suhas/research360engine/StrategyEngine.java'
s=p.read_text()
s=s.replace('        if("OWN_MODEL_INTRADAY".equals(s.category)) x+=4;\n        if("SECTOR_MOMENTUM_INTRADAY".equals(s.category)) x+=2;\n','',1)
s=s.replace('        // Scanner-origin scores are priors, not certainty. Blend rather than overwrite them.\n        if(("OWN_MODEL_INTRADAY".equals(s.category)||"SECTOR_MOMENTUM_INTRADAY".equals(s.category))&&s.score>0)x=.55*s.score+.45*x;\n','',1)
# Research360 only: tighter threshold range.
pat=r'    public double qualifyThreshold\(Db\.Signal s\) \{.*?\n    \}'
rep='''    public double qualifyThreshold(Db.Signal s) {\n        double t="QUANT_INTRADAY".equals(s.category)?82:("MOST_INTRADAY_CASH".equals(s.category)?83:84);\n        Db.CategoryStats cs=db.categoryStats(s.category);\n        if(cs.trades>=20){ if(cs.winRate()>=.68&&cs.avgNet>80)t-=2; if(cs.winRate()<.52||cs.avgNet<20)t+=3; }\n        return clamp(t,80,88);\n    }'''
s2,n=re.subn(pat,rep,s,count=1,flags=re.S)
if n!=1: raise SystemExit('qualifyThreshold patch failed')
s=s2
p.write_text(s)

# ---------- EngineService: remove next-day + sector runtime completely ----------
p=root/'app/src/main/java/com/suhas/research360engine/EngineService.java'
s=p.read_text()
s=s.replace('private ScheduledExecutorService scheduler,scannerScheduler,ipScheduler,healthScheduler;private GrowwClient groww;private Db db;private StrategyEngine strategy;private MarketScanner scanner;private SectorMomentumScanner sectorScanner;private IpGuard ipGuard;',
            'private ScheduledExecutorService scheduler,ipScheduler,healthScheduler;private GrowwClient groww;private Db db;private StrategyEngine strategy;private IpGuard ipGuard;',1)
s=s.replace('private final AtomicBoolean runningTick=new AtomicBoolean(false),runningScan=new AtomicBoolean(false);',
            'private final AtomicBoolean runningTick=new AtomicBoolean(false);',1)
s=s.replace('super.onCreate();LearningBackup.autoRestoreIfFresh(this); db=Db.get(this);AppState.migrateV14(this,db.rawNotificationCount());db.purgeLegacyNotificationNoise();groww=new GrowwClient(this);strategy=new StrategyEngine(this);scanner=new MarketScanner(this,groww);sectorScanner=new SectorMomentumScanner(this,groww);ipGuard=new IpGuard(this);',
            'super.onCreate();LearningBackup.autoRestoreIfFresh(this); db=Db.get(this);AppState.migrateV14(this,db.rawNotificationCount());db.purgeLegacyNotificationNoise();db.disableRemovedEngines();groww=new GrowwClient(this);strategy=new StrategyEngine(this);ipGuard=new IpGuard(this);',1)
s=re.sub(r'\n\s*scannerScheduler=Executors\.newSingleThreadScheduledExecutor\(.*?TimeUnit\.SECONDS\);','',s,count=1)
s=s.replace('for(ScheduledExecutorService s:new ScheduledExecutorService[]{scheduler,scannerScheduler,ipScheduler,healthScheduler})',
            'for(ScheduledExecutorService s:new ScheduledExecutorService[]{scheduler,ipScheduler,healthScheduler})',1)
# remove scanSafe method
s=re.sub(r'\n\s*private void scanSafe\(\)\{.*?\}\n','\n',s,count=1,flags=re.S)
s=s.replace('Db.Stats stats=db.stats();int rc=stats.r360Confidence(),oc=stats.ownConfidence();','Db.Stats stats=db.stats();int rc=stats.r360Confidence();',1)
s=s.replace('updateForeground(statusText(rc,oc,stats))','updateForeground(statusText(rc,stats))')
s=s.replace('updateForeground(statusText(stats.r360Confidence(),stats.ownConfidence(),stats))','updateForeground(statusText(stats.r360Confidence(),stats))')
# final conservative analyst gate before notification/shadow/live qualification
needle='double threshold=strategy.qualifyThreshold(s);if(sc<threshold){db.setSignalStatus(s.id,"WATCH");return;}String product=strategy.product(s);'
replacement='double threshold=Math.max(82.0,strategy.qualifyThreshold(s));if(sc<threshold){db.setSignalStatus(s.id,"WATCH");return;}String analystWhy=analystRejectReason(s,q,sc);if(!analystWhy.isEmpty()){db.setSignalStatus(s.id,"WATCH");db.log("ANALYST-FILTER",s.symbol+" held internally: "+analystWhy);return;}String product=strategy.product(s);'
if needle not in s: raise SystemExit('Engine qualification marker missing')
s=s.replace(needle,replacement,1)
# Only R360 evidence can unlock autonomous live.
pat=r'    private boolean sourceGate\(Db\.Stats s,String c\)\{.*?\}'
s,n=re.subn(pat,'    private boolean sourceGate(Db.Stats s,String c){return s.r360GateReady();}',s,count=1,flags=re.S)
if n!=1: raise SystemExit('sourceGate patch failed')
# Add analyst gate helper before guardsHealthyNow
marker='    private boolean guardsHealthyNow(String symbol){'
helper='''    private String analystRejectReason(Db.Signal s,Db.MarketSnapshot q,double score){\n        if(q.ltp<=0)return "no live price";\n        if(q.spreadBps>25)return String.format(Locale.US,"spread %.1fbps too wide",q.spreadBps);\n        if(q.depthImbalance<-.15)return String.format(Locale.US,"seller-heavy depth %.2f",q.depthImbalance);\n        if(q.averagePrice>0){double ext=(q.ltp/q.averagePrice-1)*100.0;if(ext>1.8)return String.format(Locale.US,"late/extended %.2f%% above average price",ext);if(ext<-.35)return String.format(Locale.US,"below average price %.2f%%",ext);}\n        if(q.rangePosition>.95&&q.dayChangePct>1.5)return String.format(Locale.US,"late chase near day high (range %.0f%%)",q.rangePosition*100.0);\n        if(q.dayChangePct>5.0)return String.format(Locale.US,"already up %.2f%% today",q.dayChangePct);\n        if(!"MOST_OVERNIGHT".equals(s.category)&&System.currentTimeMillis()-s.ts>45L*60L*1000L)return "intraday call is stale (>45 min)";\n        return "";\n    }\n\n'''
if marker not in s: raise SystemExit('guards marker missing')
s=s.replace(marker,helper+marker,1)
# Foreground copy Research360 only
s=re.sub(r'    private String statusText\(int r,int o,Db\.Stats s\)\{.*?\}',
         '    private String statusText(int r,Db.Stats s){String live=AppState.liveOrders(this)?"AUTO LIVE ENABLED":"AUTO LIVE OFF";String ip=ipGuard.cachedVerified(180000)?"IP VERIFIED":"IP CHECK";return "ARMED • "+live+" • R360 "+r+"% • "+ip;}',s,count=1,flags=re.S)
s=s.replace('private String sourceName(String c){if("OWN_MODEL_INTRADAY".equals(c))return"OWN MODEL";if("SECTOR_MOMENTUM_INTRADAY".equals(c))return"SECTOR";return"R360 FILTER";}',
            'private String sourceName(String c){return"R360 FILTER";}',1)
s=s.replace('c.setDescription("Research360 learning, scanners, static-IP guard and trading safety status")',
            'c.setDescription("Research360 notification analysis, static-IP guard and trading safety status")',1)
s=s.replace('Research360 Intelligence v1.4','Research360 Intelligence v1.8')
s=s.replace('Research360 Intelligence v1.4 engine started • notification dedupe + Groww sector oracle + auto IP/API health',
            'Research360 Intelligence v1.8 engine started • Research360-only actionable pipeline • auto IP/API health')
p.write_text(s)

# ---------- MainActivity: single-purpose actionable R360 UI ----------
p=root/'app/src/main/java/com/suhas/research360engine/MainActivity.java'
s=p.read_text()
s=s.replace('v1.7 • LG G7 ThinQ • persistent learning • responsive manual BUY/recheck • positive-sector scanner',
            'v1.8 • LG G7 ThinQ • Research360-only analytical filter • persistent learning',1)
# one confidence card only
pat=r'        LinearLayout confRow=.*?space\(root,10\);\n\n        LinearLayout state='
rep='''        LinearLayout confRow=new LinearLayout(this);confRow.setOrientation(LinearLayout.HORIZONTAL);LinearLayout left=miniCard();left.addView(text("RESEARCH360 ENGINE CONFIDENCE",10,MUTED,true));r360Confidence=text("0%",30,ACCENT,true);left.addView(r360Confidence);r360Maturity=text("evidence maturity 0%",10,MUTED,false);left.addView(r360Maturity);confRow.addView(left,new LinearLayout.LayoutParams(-1,-2));root.addView(confRow);space(root,10);\n\n        LinearLayout state='''
s2,n=re.subn(pat,rep,s,count=1,flags=re.S)
if n!=1: raise SystemExit('confidence UI patch failed')
s=s2
# control copy and gate only Research360
s=s.replace('ARM RESEARCH360 + MARKET LEARNING','ARM RESEARCH360 ANALYSIS',1)
s=s.replace('ARM ON captures only validated Research360 stock-call messages, learns in shadow mode, scans the independent market model and runs the isolated Groww sector engine.',
            'ARM ON captures validated Research360 stock calls and continuously re-checks them against live Groww price, spread, order-book pressure, average-price extension, range position, charges and our historical Research360 outcomes. Rejected/WATCH candidates stay internal.',1)
s=s.replace('if(!AppState.isArmed(this)||!s.anyLiveGateReady())','if(!AppState.isArmed(this)||!s.r360GateReady())',1)
s=s.replace('At least one isolated source needs ≥80% calibrated confidence, enough resolved shadow trades, positive net expectancy and the required win rate. Manual BUY remains available only on a current qualified recommendation.',
            'Research360 autonomous live needs ≥80% calibrated confidence, at least 50 resolved shadow trades, positive net expectancy and ≥60% ₹100-net win rate. Manual BUY remains available only on a current qualified recommendation.',1)
s=s.replace('This enables automatic orders only for evidence-ready model compartments. One live position at a time.',
            'This enables automatic orders only for the evidence-ready Research360 filter. One live position at a time.',1)
# actionable section name/copy
s=s.replace('RESEARCH360 PICKS — TODAY TOP 5','RESEARCH360 — ACTIONABLE BUYS',1)
s=s.replace('Only validated stock-call notifications appear here. Research360 target/SL never controls our BUY decision or exit. BUY uses our revalidated price/score and asks for a rupee amount.',
            'Research360 calls are raw inputs and remain hidden until OUR live analytical gate passes. If this section is empty, the correct action is WAIT. A visible BUY means the engine has already qualified the setup; tapping it still revalidates live price/API/static IP before any real order.',1)
# remove own-model and sector cards completely
pat=r'\n        LinearLayout next=card\(root\);.*?space\(root,10\);\n\n        LinearLayout sector=card\(root\);.*?space\(root,10\);\n\n        LinearLayout risk='
s2,n=re.subn(pat,'\n        LinearLayout risk=',s,count=1,flags=re.S)
if n!=1: raise SystemExit('own/sector UI removal failed')
s=s2
# backup/device text no longer advertises removed engines
s=s.replace('It contains signals, market snapshots, shadow/live outcomes, sector learning, predictions and useful logs so the learning survives an uninstall.',
            'It contains validated Research360 signals, market snapshots, shadow/live outcomes, calibrated scores and useful logs so the learning survives an uninstall.',1)
s=s.replace('v1.7 ignores generic Research360 app notifications','v1.8 ignores generic Research360 app notifications')
s=s.replace('v1.7 re-verifies the actual public egress IP','v1.8 re-verifies the actual public egress IP')
s=s.replace('Before sending, v1.7 rechecks the score, Groww API and exact static IP.','Before sending, v1.8 rechecks the score, Groww API and exact static IP.')
# refresh only R360; leave unused fields declared but never touched
pat=r'Db\.Stats s=Db\.get\(this\)\.stats\(\);int rc=s\.r360Confidence\(\),oc=s\.ownConfidence\(\),sc=s\.sectorConfidence\(\);.*?sectorConfidence\.setTextColor\(sc>=80\?GREEN:ACCENT\);'
rep='Db.Stats s=Db.get(this).stats();int rc=s.r360Confidence();r360Confidence.setText(rc+"%");r360Maturity.setText("evidence maturity "+s.r360Maturity()+"% • "+s.r360ShadowTrades+" resolved shadow trades");r360Confidence.setTextColor(rc>=80?GREEN:ACCENT);'
s2,n=re.subn(pat,rep,s,count=1,flags=re.S)
if n!=1: raise SystemExit('refresh confidence patch failed')
s=s2
pat=r'gate\.setText\(String\.format\(Locale\.US,"R360:.*?s\.sectorShadowNet\)\);'
rep='gate.setText(Db.get(this).r360TodayPipeline()+String.format(Locale.US,"\\nEvidence: %d resolved shadow • %.1f%% ₹100-net wins • ₹%.0f cumulative net",s.r360ShadowTrades,s.r360WinRate()*100,s.r360ShadowNet));'
s2,n=re.subn(pat,rep,s,count=1,flags=re.S)
if n!=1: raise SystemExit('gate patch failed')
s=s2
s=s.replace('renderRecommendations(r360Rows,Db.get(this).todayR360Top5(),"Waiting for validated Research360 BUY calls…");ownTop.setText(formatOwn(Db.get(this).latestPredictions()));sectorSummary.setText(AppState.sectorSummary(this));renderRecommendations(sectorRows,Db.get(this).todaySectorTop5(),"No qualified stock across today\'s positive Groww sectors yet.");',
            'renderRecommendations(r360Rows,Db.get(this).actionableR360Now(),"NO ACTIONABLE BUY RIGHT NOW • Research360 calls are still being analysed internally.");',1)
# stats panel R360 only
pat=r'stats\.setText\(String\.format\(Locale\.US,"Validated R360 stock messages: %d\\nParsed R360 signals: %d • resolved: %d\\nR360 shadow: %d trades • %d ₹100-net wins • ₹%.2f\\nOwn shadow: %d trades • %d wins • ₹%.2f\\nSector shadow: %d trades • %d wins • ₹%.2f\\nLive net today: ₹%.2f\\nBudget: ₹%.0f • Daily loss ceiling: ₹%.0f\\nLegacy raw callback spam is not counted as model evidence\.",.*?\)\);'
rep='stats.setText(String.format(Locale.US,"Validated R360 stock messages: %d\\nParsed R360 signals: %d • resolved observations: %d\\nQualified R360 shadow trades: %d • %d ₹100-net wins • ₹%.2f\\nR360 confidence: %d%% • evidence maturity: %d%%\\nLive net today: ₹%.2f\\nBudget: ₹%.0f • Daily loss ceiling: ₹%.0f\\nWATCH/rejected calls remain internal and do not appear as recommendations.",s.notifications,s.parsed,s.resolvedSignals,s.r360ShadowTrades,s.r360ShadowWins,s.r360ShadowNet,s.r360Confidence(),s.r360Maturity(),s.liveNetToday,AppState.budget(this),AppState.dailyLossLimit(this)));'
s2,n=re.subn(pat,rep,s,count=1,flags=re.S)
if n!=1: raise SystemExit('stats patch failed')
s=s2
# Recommendation labels: only qualified active rows reach this UI.
s=s.replace('if(x.contains("NEW")||x.contains("WATCH")||x.contains("SHADOW_ACTIVE"))return"BUY";',
            'if(x.contains("SHADOW_ACTIVE"))return"BUY NOW";if(x.contains("NEW")||x.contains("WATCH"))return"WAIT";',1)
s=s.replace('if(x.contains("NEW")||x.contains("WATCH")||x.contains("SHADOW_ACTIVE"))return ACCENT;',
            'if(x.contains("SHADOW_ACTIVE"))return GREEN;if(x.contains("NEW")||x.contains("WATCH"))return ACCENT;',1)
# In visible detail, SHADOW_ACTIVE means our model has qualified it, not merely "shadow".
s=s.replace('r.status),10,statusColor(r.status),false);','displayStatus(r.status)),10,statusColor(r.status),false);',1)
marker='    private static boolean isLiveActive(String s){'
helper='''    private String displayStatus(String s){if(s==null)return"";if(s.contains("SHADOW_ACTIVE"))return"BUY QUALIFIED";if(s.contains("LIVE_ACTIVE"))return"LIVE POSITION";return s;}\n'''
if marker in s:s=s.replace(marker,helper+marker,1)
# remove formatOwn helper safely if present (not required, but keeps binary focused)
s=re.sub(r'\n    private String formatOwn\(List<Db\.Prediction> x\)\{.*?\n    private static String pretty', '\n    private static String pretty', s, count=1, flags=re.S)
p.write_text(s)

# ---------- Learning backup: stop exporting removed model tables ----------
p=root/'app/src/main/java/com/suhas/research360engine/LearningBackup.java'
s=p.read_text()
s=s.replace('private static final String[] TABLES={"notifications","signals","snapshots","trades","predictions","sector_meta","logs"};',
            'private static final String[] TABLES={"notifications","signals","snapshots","trades","logs"};',1)
s=s.replace('root.put("backup_format",1);root.put("app_version","1.7.0");',
            'root.put("backup_format",1);root.put("app_version","1.8.0");',1)
p.write_text(s)

# ---------- static contract ----------
checks=[
    (root/'app/build.gradle',"versionName '1.8.0'"),
    (root/'app/src/main/java/com/suhas/research360engine/MainActivity.java','RESEARCH360 — ACTIONABLE BUYS'),
    (root/'app/src/main/java/com/suhas/research360engine/MainActivity.java','NO ACTIONABLE BUY RIGHT NOW'),
    (root/'app/src/main/java/com/suhas/research360engine/Db.java','actionableR360Now'),
    (root/'app/src/main/java/com/suhas/research360engine/Db.java','r360ShadowTrades>=50'),
    (root/'app/src/main/java/com/suhas/research360engine/EngineService.java','analystRejectReason'),
]
for f,t in checks:
    if t not in f.read_text(): raise SystemExit(f'missing {t} in {f}')
main=(root/'app/src/main/java/com/suhas/research360engine/MainActivity.java').read_text()
if 'OWN MODEL — NEXT SESSION TOP 5' in main or 'POSITIVE SECTORS — BEST 5 STOCKS' in main: raise SystemExit('removed model UI still present')
eng=(root/'app/src/main/java/com/suhas/research360engine/EngineService.java').read_text()
if 'scannerScheduler.scheduleWithFixedDelay' in eng or 'sectorScanner.maybeRun' in eng or 'scanner.maybeRun' in eng: raise SystemExit('removed scanners still scheduled')
print('v1.8 Research360-only patch applied')
