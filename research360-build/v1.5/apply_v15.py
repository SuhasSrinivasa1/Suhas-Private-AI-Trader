from pathlib import Path
import re

root=Path('/tmp/r360')

# ---------- build.gradle ----------
p=root/'app/build.gradle'
s=p.read_text()
s=re.sub(r"versionCode\s+\d+","versionCode 150",s,count=1)
s=re.sub(r"versionName\s+'[^']+'","versionName '1.5.0'",s,count=1)
p.write_text(s)

# ---------- MainActivity: stable scrolling + Top 5 positive sectors ----------
p=root/'app/src/main/java/com/suhas/research360engine/MainActivity.java'
s=p.read_text()
if 'import android.view.ViewGroup;' not in s:
    s=s.replace('import android.view.View;\n','import android.view.View;\nimport android.view.ViewGroup;\n',1)

s=s.replace('private LinearLayout r360Rows,sectorRows;private Switch armed,live;',
            'private LinearLayout r360Rows,sectorRows;private ScrollView mainScroll;private Switch armed,live;',1)

s=s.replace('ScrollView scroll=new ScrollView(this);',
            'mainScroll=new ScrollView(this);ScrollView scroll=mainScroll;',1)
s=s.replace('scroll.addView(root);',
            'scroll.setFillViewport(true);scroll.setSmoothScrollingEnabled(false);scroll.setFocusableInTouchMode(true);scroll.setDescendantFocusability(ViewGroup.FOCUS_BEFORE_DESCENDANTS);scroll.addView(root);scroll.requestFocus();',1)

s=s.replace('v1.4 • LG G7 ThinQ • validated R360 calls + independent market model + Groww sector oracle',
            'v1.5 • LG G7 ThinQ • validated R360 calls + independent model + all-positive-sector scanner',1)

s=s.replace('GROWW TRENDING SECTOR — TOP 3','POSITIVE SECTORS — GLOBAL TOP 5',1)
s=s.replace("The sector itself comes from Groww's Trending sectors 1D-price-change table. If that Groww row cannot be verified, this module fails closed instead of guessing a bank/sector. Learning stays SECTOR ONLY.",
            "Every Groww sector with a positive 1D price change is scanned. The app then ranks the five best executable stocks across the union of all green sectors. Sector learning remains isolated and persists across days.",1)
s=s.replace('Waiting for Groww sector confirmation after market open…','Waiting for the all-positive-sector scan after market open…',1)
s=s.replace('Db.get(this).todaySectorTop3()','Db.get(this).todaySectorTop5()')
s=s.replace('No verified sector trade candidate yet.','No qualified stock across today\'s positive Groww sectors yet.')

s=s.replace('handler.postDelayed(this,2000);','handler.postDelayed(this,5000);',1)
s=s.replace('private void refresh(){\n        Db.Stats s=Db.get(this).stats();',
            'private void refresh(){\n        final int keepY=mainScroll==null?0:mainScroll.getScrollY();\n        Db.Stats s=Db.get(this).stats();',1)

needle='internalToggle=true;armed.setChecked(AppState.isArmed(this));live.setChecked(AppState.liveOrders(this));internalToggle=false;\n    }\n\n    private void renderRecommendations'
repl='internalToggle=true;armed.setChecked(AppState.isArmed(this));live.setChecked(AppState.liveOrders(this));internalToggle=false;if(mainScroll!=null&&!editingField()){final int restoreY=keepY;mainScroll.post(()->mainScroll.scrollTo(0,restoreY));}\n    }\n\n    private boolean editingField(){return getCurrentFocus() instanceof EditText;}\n\n    private void renderRecommendations'
if needle not in s:
    raise SystemExit('MainActivity refresh tail marker not found')
s=s.replace(needle,repl,1)

old='TextView t=text(String.format(Locale.US,"%d. %s\\n%.0f%% • %s • %s",rank++,r.symbol,r.score,pretty(r.category),r.status),11,Color.WHITE,false);'
new='String rowLabel=(r.sector==null||r.sector.isEmpty())?pretty(r.category):(r.sector+" • "+pretty(r.category));TextView t=text(String.format(Locale.US,"%d. %s\\n%.0f%% • %s • %s",rank++,r.symbol,r.score,rowLabel,r.status),11,Color.WHITE,false);'
if old not in s:
    raise SystemExit('renderRecommendations marker not found')
s=s.replace(old,new,1)

s=s.replace('logs.setTextIsSelectable(true);','logs.setTextIsSelectable(false);',1)
s=s.replace('v1.4 rechecks the score, Groww API and exact static IP.','v1.5 rechecks the score, Groww API and exact static IP.',1)
s=s.replace('v1.4 re-verifies the actual public egress IP','v1.5 re-verifies the actual public egress IP',1)
s=s.replace('v1.4 ignores generic Research360 app notifications','v1.5 ignores generic Research360 app notifications',1)
p.write_text(s)

# ---------- Db: persist sector identity + per-sector learning + Top 5 ----------
p=root/'app/src/main/java/com/suhas/research360engine/Db.java'
s=p.read_text()
s=s.replace('public static final int VERSION = 4;','public static final int VERSION = 5;',1)
s=s.replace('createV1(db);createPredictions(db);','createV1(db);createPredictions(db);createSectorMeta(db);',1)

marker='    @Override public void onUpgrade(SQLiteDatabase db, int oldVersion, int newVersion) { if(oldVersion<2)createPredictions(db); }'
insert='''    private void createSectorMeta(SQLiteDatabase db){\n        db.execSQL("CREATE TABLE IF NOT EXISTS sector_meta (signal_id INTEGER PRIMARY KEY, sector TEXT, sector_change REAL DEFAULT 0, stock_change REAL DEFAULT 0, scan_ts INTEGER)");\n        db.execSQL("CREATE INDEX IF NOT EXISTS idx_sector_meta_sector ON sector_meta(sector)");\n    }\n    @Override public void onUpgrade(SQLiteDatabase db, int oldVersion, int newVersion) { if(oldVersion<2)createPredictions(db);if(oldVersion<5)createSectorMeta(db); }'''
if marker not in s:
    raise SystemExit('Db upgrade marker not found')
s=s.replace(marker,insert,1)

marker='    public boolean hasRecentSignal(String category,String action,String symbol,double entry,long sinceTs){'
insert='''    public long insertSectorSignal(String symbol,double entry,double modelScore,String sector,double sectorChange,double stockChange){\n        long sid=insertModelSignal("SECTOR_MOMENTUM_INTRADAY",symbol,entry,modelScore);\n        if(sid>0){ContentValues v=new ContentValues();v.put("signal_id",sid);v.put("sector",sector==null?"":sector);v.put("sector_change",sectorChange);v.put("stock_change",stockChange);v.put("scan_ts",System.currentTimeMillis());getWritableDatabase().insertWithOnConflict("sector_meta",null,v,SQLiteDatabase.CONFLICT_REPLACE);}\n        return sid;\n    }\n\n'''+marker
if marker not in s:
    raise SystemExit('Db hasRecentSignal marker not found')
s=s.replace(marker,insert,1)

pattern=r'    public List<Recommendation> todaySectorTop3\(\)\{.*?return out;\}\n'
replacement='''    public List<Recommendation> todaySectorTop5(){long start=LocalDate.now(IST).atStartOfDay(IST).toInstant().toEpochMilli();ArrayList<Recommendation> out=new ArrayList<>();Set<String> seen=new HashSet<>();Cursor c=getReadableDatabase().rawQuery("SELECT sg.id,sg.symbol,sg.category,sg.score,sg.status,sg.entry,sg.mfe,sg.mae,sg.ts,COALESCE(sm.sector,'') FROM signals sg LEFT JOIN sector_meta sm ON sm.signal_id=sg.id WHERE sg.action='BUY' AND sg.ts>=? AND sg.category='SECTOR_MOMENTUM_INTRADAY' AND sg.symbol!='' ORDER BY sg.score DESC,sg.ts DESC",new String[]{String.valueOf(start)});try{while(c.moveToNext()&&out.size()<5){String sym=c.getString(1);if(!seen.add(sym))continue;Recommendation r=new Recommendation();r.id=c.getLong(0);r.symbol=sym;r.category=c.getString(2);r.score=c.getDouble(3);r.status=c.getString(4);r.entry=c.getDouble(5);r.mfe=c.getDouble(6);r.mae=c.getDouble(7);r.sector=c.getString(9);out.add(r);}}finally{c.close();}return out;}\n'''
s2,n=re.subn(pattern,replacement,s,count=1,flags=re.S)
if n!=1:
    raise SystemExit('Db todaySectorTop3 replacement failed')
s=s2

marker='    public PatternStats successfulR360Pattern(){'
insert='''    public SectorPerf sectorPerf(String sector){SectorPerf p=new SectorPerf();if(sector==null||sector.isEmpty())return p;Cursor c=getReadableDatabase().rawQuery("SELECT COUNT(*),COALESCE(SUM(CASE WHEN t.net_pnl>=100 THEN 1 ELSE 0 END),0),COALESCE(AVG(t.net_pnl),0) FROM trades t JOIN sector_meta sm ON sm.signal_id=t.signal_id WHERE t.mode='SHADOW' AND t.status='CLOSED' AND sm.sector=?",new String[]{sector});try{if(c.moveToFirst()){p.trades=c.getLong(0);p.wins=c.getLong(1);p.avgNet=c.getDouble(2);}}finally{c.close();}return p;}\n\n'''+marker
if marker not in s:
    raise SystemExit('Db pattern stats marker not found')
s=s.replace(marker,insert,1)

old='public static final class Recommendation{public long id;public String symbol="",category="",status="";public double score,entry,mfe,mae;'
new='public static final class Recommendation{public long id;public String symbol="",category="",status="",sector="";public double score,entry,mfe,mae;'
if old not in s:
    raise SystemExit('Recommendation marker not found')
s=s.replace(old,new,1)

marker='    public static final class PatternStats{public long n;public double depth,spread,range,dayChange;}'
insert='    public static final class SectorPerf{public long trades,wins;public double avgNet;public double winRate(){return trades==0?0:(double)wins/trades;}}\n'+marker
if marker not in s:
    raise SystemExit('PatternStats class marker not found')
s=s.replace(marker,insert,1)
p.write_text(s)

# ---------- replace sector scanner ----------
sector_src=Path('/workspace/research360-build/v1.5/SectorMomentumScanner.java')
if not sector_src.exists():
    # GitHub Actions workspace path
    sector_src=Path.cwd()/'research360-build/v1.5/SectorMomentumScanner.java'
if not sector_src.exists():
    raise SystemExit('v1.5 sector source not found')
(root/'app/src/main/java/com/suhas/research360engine/SectorMomentumScanner.java').write_text(sector_src.read_text())

# Basic static validation
checks=[
    (root/'app/build.gradle',"versionName '1.5.0'"),
    (root/'app/src/main/java/com/suhas/research360engine/MainActivity.java','POSITIVE SECTORS — GLOBAL TOP 5'),
    (root/'app/src/main/java/com/suhas/research360engine/MainActivity.java','todaySectorTop5()'),
    (root/'app/src/main/java/com/suhas/research360engine/Db.java','VERSION = 5'),
    (root/'app/src/main/java/com/suhas/research360engine/Db.java','sector_meta'),
    (root/'app/src/main/java/com/suhas/research360engine/SectorMomentumScanner.java','parsePositiveSectors'),
]
for f,t in checks:
    if t not in f.read_text():raise SystemExit(f'missing {t} in {f}')
print('v1.5 patch applied')
