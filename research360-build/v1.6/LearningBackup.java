package com.suhas.research360engine;

import android.Manifest;
import android.content.ContentResolver;
import android.content.ContentUris;
import android.content.ContentValues;
import android.content.Context;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.provider.MediaStore;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedInputStream;
import java.io.BufferedOutputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.time.LocalDate;
import java.time.LocalTime;
import java.time.ZoneId;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;
import java.util.zip.ZipOutputStream;

/**
 * Persistent, user-visible learning backup.
 *
 * One rolling file is kept in Downloads:
 *   Research360-Intelligence-Learning-LATEST.zip
 *
 * The file contains the learning database as JSON plus a human-readable diagnostic report.
 * Groww API keys, TOTP secrets and access tokens are deliberately NOT exported.
 */
public final class LearningBackup {
    public static final String FILE_NAME="Research360-Intelligence-Learning-LATEST.zip";
    private static final String TEMP_NAME="Research360-Intelligence-Learning-WRITING.tmp.zip";
    private static final String PREF="r360_backup_state";
    private static final String K_LAST="last_backup_at";
    private static final String K_LAST_REASON="last_backup_reason";
    private static final String K_LAST_FP="last_backup_fingerprint";
    private static final String K_FINAL_DAY="last_session_backup_day";
    private static final String K_RESTORE="last_restore_at";
    private static final ZoneId IST=ZoneId.of("Asia/Kolkata");
    private static final Object LOCK=new Object();
    private static final long CHECKPOINT_MS=15L*60L*1000L;
    private static final String[] TABLES={"notifications","signals","snapshots","trades","predictions","sector_meta","logs"};

    private LearningBackup(){}

    public static final class Result{
        public final boolean ok;public final String message;public final long rows;
        Result(boolean o,String m,long r){ok=o;message=m;rows=r;}
    }

    public static boolean storageReady(Context c){
        if(Build.VERSION.SDK_INT>=29)return true;
        return c.checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE)==PackageManager.PERMISSION_GRANTED
                &&c.checkSelfPermission(Manifest.permission.READ_EXTERNAL_STORAGE)==PackageManager.PERMISSION_GRANTED;
    }

    public static String status(Context c){
        SharedPreferences p=c.getSharedPreferences(PREF,Context.MODE_PRIVATE);long at=p.getLong(K_LAST,0);
        String when=at<=0?"never":Instant.ofEpochMilli(at).atZone(IST).toLocalDateTime().toString().replace('T',' ');
        String reason=p.getString(K_LAST_REASON,"");
        return "Downloads / "+FILE_NAME+"\nLast backup: "+when+(reason.isEmpty()?"":" • "+reason)+"\n"+
                (storageReady(c)?"Storage access: READY":"Storage access: PERMISSION REQUIRED");
    }

    /** Called by the background engine. It is cheap unless a backup is actually due. */
    public static void maybeBackup(Context c){
        synchronized(LOCK){
            try{
                if(!storageReady(c))return;
                long rows=learningRows(c);if(rows<=0)return;
                long now=System.currentTimeMillis();SharedPreferences p=c.getSharedPreferences(PREF,Context.MODE_PRIVATE);
                String fp=fingerprint(c);String old=p.getString(K_LAST_FP,"");long last=p.getLong(K_LAST,0);
                LocalTime t=LocalTime.now(IST);String today=LocalDate.now(IST).toString();
                boolean finalDue=!t.isBefore(LocalTime.of(15,35))&&!today.equals(p.getString(K_FINAL_DAY,""));
                boolean checkpointDue=now-last>=CHECKPOINT_MS&&!fp.equals(old);
                if(!finalDue&&!checkpointDue)return;
                Result r=backupNowLocked(c,finalDue?"SESSION_CLOSE":"15_MIN_CHECKPOINT",fp);
                if(r.ok&&finalDue)p.edit().putString(K_FINAL_DAY,today).apply();
            }catch(Exception e){try{Db.get(c).log("BACKUP","Automatic backup failed: "+shortMsg(e));}catch(Exception ignored){}}
        }
    }

    public static Result backupNow(Context c,String reason){
        synchronized(LOCK){
            try{return backupNowLocked(c,reason==null?"MANUAL":reason,fingerprint(c));}
            catch(Exception e){try{Db.get(c).log("BACKUP","Backup failed: "+shortMsg(e));}catch(Exception ignored){}return new Result(false,"Backup failed: "+shortMsg(e),0);}
        }
    }

    private static Result backupNowLocked(Context c,String reason,String fp)throws Exception{
        if(!storageReady(c))return new Result(false,"Downloads permission is required on this Android version",0);
        JSONObject root=new JSONObject();root.put("backup_format",1);root.put("app_version","1.6.0");root.put("exported_at",System.currentTimeMillis());root.put("exported_at_ist",Instant.now().atZone(IST).toLocalDateTime().toString());root.put("reason",reason);
        JSONObject tables=new JSONObject();long total=0;
        for(String table:TABLES){JSONArray rows=exportTable(c,table);tables.put(table,rows);total+=rows.length();}
        root.put("tables",tables);root.put("preferences",exportSafePreferences(c));root.put("diagnostics",diagnosticsJson(c));
        byte[] json=root.toString().getBytes(StandardCharsets.UTF_8);byte[] diag=diagnosticsText(c,reason,total).getBytes(StandardCharsets.UTF_8);
        writeZip(c,json,diag);
        long now=System.currentTimeMillis();c.getSharedPreferences(PREF,Context.MODE_PRIVATE).edit().putLong(K_LAST,now).putString(K_LAST_REASON,reason).putString(K_LAST_FP,fp).apply();
        try{Db.get(c).log("BACKUP","Learning backup updated in Downloads • "+reason+" • "+total+" rows");}catch(Exception ignored){}
        return new Result(true,"Backup saved to Downloads / "+FILE_NAME,total);
    }

    /** Automatically restores only when the installed app has no learning yet. */
    public static Result autoRestoreIfFresh(Context c){
        synchronized(LOCK){
            try{
                if(!storageReady(c))return new Result(false,"Storage permission not available",0);
                if(learningRows(c)>0)return new Result(false,"Existing learning retained",0);
                if(!backupExists(c))return new Result(false,"No prior Downloads backup found",0);
                return restoreLatestLocked(c,true);
            }catch(Exception e){return new Result(false,"Auto-restore skipped: "+shortMsg(e),0);}
        }
    }

    public static Result restoreLatestIfFresh(Context c){
        synchronized(LOCK){
            try{return restoreLatestLocked(c,true);}catch(Exception e){return new Result(false,"Restore failed: "+shortMsg(e),0);}
        }
    }

    private static Result restoreLatestLocked(Context c,boolean requireFresh)throws Exception{
        if(!storageReady(c))return new Result(false,"Downloads permission is required",0);
        if(AppState.liveOrders(c))return new Result(false,"Turn autonomous LIVE orders OFF before restoring",0);
        if(Db.get(c).openLiveTrade()!=null)return new Result(false,"Cannot restore while a live trade is open",0);
        long existing=learningRows(c);if(requireFresh&&existing>0)return new Result(false,"Restore blocked: this installation already contains learning. Existing learning was not overwritten.",existing);
        byte[] backupJson=readZipEntry(c,"backup.json");if(backupJson==null)throw new IllegalStateException("backup.json missing");
        JSONObject root=new JSONObject(new String(backupJson,StandardCharsets.UTF_8));if(root.optInt("backup_format",0)!=1)throw new IllegalStateException("Unsupported backup format");
        JSONObject tables=root.optJSONObject("tables");if(tables==null)throw new IllegalStateException("Learning tables missing");
        SQLiteDatabase db=Db.get(c).getWritableDatabase();db.beginTransaction();long restored=0;
        try{
            // Child tables first, then parents. No foreign keys are declared, but this ordering stays safe.
            for(String t:new String[]{"sector_meta","snapshots","trades","predictions","signals","logs","notifications"})if(tableExists(db,t))db.delete(t,null,null);
            for(String t:new String[]{"notifications","signals","snapshots","trades","predictions","sector_meta","logs"}){
                JSONArray a=tables.optJSONArray(t);if(a==null||!tableExists(db,t))continue;Set<String> columns=columns(db,t);
                for(int i=0;i<a.length();i++){JSONObject row=a.optJSONObject(i);if(row==null)continue;ContentValues v=new ContentValues();for(String k:columns){if(!row.has(k)||row.isNull(k))continue;Object x=row.opt(k);put(v,k,x);}db.insertWithOnConflict(t,null,v,SQLiteDatabase.CONFLICT_REPLACE);restored++;}
            }
            db.setTransactionSuccessful();
        }finally{db.endTransaction();}
        importSafePreferences(c,root.optJSONObject("preferences"));c.getSharedPreferences(PREF,Context.MODE_PRIVATE).edit().putLong(K_RESTORE,System.currentTimeMillis()).apply();
        try{Db.get(c).log("BACKUP","Learning restored from Downloads • "+restored+" rows");}catch(Exception ignored){}
        return new Result(true,"Learning restored from "+FILE_NAME,restored);
    }

    private static JSONArray exportTable(Context c,String table)throws Exception{
        SQLiteDatabase db=Db.get(c).getReadableDatabase();if(!tableExists(db,table))return new JSONArray();
        String sql="SELECT * FROM "+table;
        if("notifications".equals(table))sql="SELECT * FROM notifications WHERE id IN (SELECT notification_id FROM signals WHERE notification_id>0)";
        else if("logs".equals(table))sql="SELECT * FROM logs ORDER BY id DESC LIMIT 5000";
        Cursor cur=db.rawQuery(sql,null);JSONArray out=new JSONArray();try{String[] cols=cur.getColumnNames();while(cur.moveToNext()){JSONObject r=new JSONObject();for(int i=0;i<cols.length;i++){switch(cur.getType(i)){case Cursor.FIELD_TYPE_NULL:r.put(cols[i],JSONObject.NULL);break;case Cursor.FIELD_TYPE_INTEGER:r.put(cols[i],cur.getLong(i));break;case Cursor.FIELD_TYPE_FLOAT:r.put(cols[i],cur.getDouble(i));break;case Cursor.FIELD_TYPE_BLOB:r.put(cols[i],android.util.Base64.encodeToString(cur.getBlob(i),android.util.Base64.NO_WRAP));break;default:r.put(cols[i],cur.getString(i));}}out.put(r);}}finally{cur.close();}return out;
    }

    private static JSONObject exportSafePreferences(Context c)throws Exception{
        JSONObject out=new JSONObject();Map<String,?> all=c.getSharedPreferences("r360_state",Context.MODE_PRIVATE).getAll();
        for(Map.Entry<String,?> e:all.entrySet()){String k=e.getKey().toLowerCase();if(k.contains("token")||k.contains("secret")||k.contains("totp")||k.contains("api_key")||k.contains("password"))continue;Object v=e.getValue();JSONObject x=new JSONObject();if(v instanceof Boolean){x.put("type","boolean");x.put("value",v);}else if(v instanceof Integer){x.put("type","int");x.put("value",v);}else if(v instanceof Long){x.put("type","long");x.put("value",v);}else if(v instanceof Float){x.put("type","float");x.put("value",((Float)v).doubleValue());}else if(v instanceof String){x.put("type","string");x.put("value",v);}else if(v instanceof Set){x.put("type","stringset");JSONArray a=new JSONArray();for(Object z:(Set<?>)v)a.put(String.valueOf(z));x.put("value",a);}else continue;out.put(e.getKey(),x);}return out;
    }

    private static void importSafePreferences(Context c,JSONObject obj)throws Exception{
        if(obj==null)return;SharedPreferences.Editor ed=c.getSharedPreferences("r360_state",Context.MODE_PRIVATE).edit();JSONArray names=obj.names();if(names==null)return;
        for(int i=0;i<names.length();i++){String k=names.optString(i);JSONObject x=obj.optJSONObject(k);if(x==null)continue;String lk=k.toLowerCase();if(lk.contains("token")||lk.contains("secret")||lk.contains("totp")||lk.contains("api_key")||lk.contains("password")||"live_orders".equals(k))continue;String type=x.optString("type","");if("boolean".equals(type))ed.putBoolean(k,x.optBoolean("value"));else if("int".equals(type))ed.putInt(k,x.optInt("value"));else if("long".equals(type))ed.putLong(k,x.optLong("value"));else if("float".equals(type))ed.putFloat(k,(float)x.optDouble("value"));else if("string".equals(type))ed.putString(k,x.optString("value",""));else if("stringset".equals(type)){JSONArray a=x.optJSONArray("value");Set<String>s=new HashSet<>();if(a!=null)for(int j=0;j<a.length();j++)s.add(a.optString(j));ed.putStringSet(k,s);}}
        ed.putBoolean("live_orders",false);ed.apply();
    }

    private static JSONObject diagnosticsJson(Context c)throws Exception{
        Db.Stats s=Db.get(c).stats();JSONObject j=new JSONObject();j.put("validated_r360_messages",s.notifications);j.put("parsed_r360_signals",s.parsed);j.put("resolved_r360_signals",s.resolvedSignals);j.put("r360_shadow_trades",s.r360ShadowTrades);j.put("r360_shadow_wins",s.r360ShadowWins);j.put("r360_shadow_net",s.r360ShadowNet);j.put("own_shadow_trades",s.ownShadowTrades);j.put("own_shadow_wins",s.ownShadowWins);j.put("own_shadow_net",s.ownShadowNet);j.put("sector_shadow_trades",s.sectorShadowTrades);j.put("sector_shadow_wins",s.sectorShadowWins);j.put("sector_shadow_net",s.sectorShadowNet);j.put("live_net_today",s.liveNetToday);j.put("budget",AppState.budget(c));j.put("daily_loss_limit",AppState.dailyLossLimit(c));j.put("recent_logs",Db.get(c).recentLogs(120));return j;
    }

    private static String diagnosticsText(Context c,String reason,long rows){Db.Stats s=Db.get(c).stats();StringBuilder b=new StringBuilder();b.append("Research360 Intelligence v1.6.0 learning backup\n");b.append("Exported IST: ").append(Instant.now().atZone(IST).toLocalDateTime()).append('\n');b.append("Reason: ").append(reason).append("\nRows in backup: ").append(rows).append("\n\n");b.append("Validated Research360 messages: ").append(s.notifications).append('\n');b.append("Parsed signals: ").append(s.parsed).append(" | Resolved: ").append(s.resolvedSignals).append('\n');b.append("R360 shadow: ").append(s.r360ShadowTrades).append(" trades | ").append(s.r360ShadowWins).append(" ₹100-net wins | ₹").append(String.format(java.util.Locale.US,"%.2f",s.r360ShadowNet)).append('\n');b.append("Own model shadow: ").append(s.ownShadowTrades).append(" trades | ").append(s.ownShadowWins).append(" wins | ₹").append(String.format(java.util.Locale.US,"%.2f",s.ownShadowNet)).append('\n');b.append("Sector shadow: ").append(s.sectorShadowTrades).append(" trades | ").append(s.sectorShadowWins).append(" wins | ₹").append(String.format(java.util.Locale.US,"%.2f",s.sectorShadowNet)).append('\n');b.append("Live net today: ₹").append(String.format(java.util.Locale.US,"%.2f",s.liveNetToday)).append("\nBudget: ₹").append(String.format(java.util.Locale.US,"%.0f",AppState.budget(c))).append(" | Daily loss ceiling: ₹").append(String.format(java.util.Locale.US,"%.0f",AppState.dailyLossLimit(c))).append("\n\nRECENT ENGINE LOG\n").append(Db.get(c).recentLogs(120));b.append("\nSECURITY NOTE\nGroww API key, TOTP secret and access token are intentionally excluded from this backup.\n");return b.toString();}

    private static long learningRows(Context c){SQLiteDatabase db=Db.get(c).getReadableDatabase();long n=0;for(String t:new String[]{"signals","snapshots","trades","predictions","sector_meta"})if(tableExists(db,t))n+=scalar(db,"SELECT COUNT(*) FROM "+t);return n;}
    private static String fingerprint(Context c){SQLiteDatabase db=Db.get(c).getReadableDatabase();StringBuilder b=new StringBuilder();for(String t:new String[]{"signals","snapshots","trades","predictions","sector_meta","logs"})if(tableExists(db,t))b.append(t).append(':').append(scalar(db,"SELECT COALESCE(MAX(id),0) FROM "+t)).append('/').append(scalar(db,"SELECT COUNT(*) FROM "+t)).append(';');return b.toString();}
    private static long scalar(SQLiteDatabase db,String sql){Cursor c=db.rawQuery(sql,null);try{return c.moveToFirst()?c.getLong(0):0;}finally{c.close();}}
    private static boolean tableExists(SQLiteDatabase db,String table){Cursor c=db.rawQuery("SELECT name FROM sqlite_master WHERE type='table' AND name=?",new String[]{table});try{return c.moveToFirst();}finally{c.close();}}
    private static Set<String> columns(SQLiteDatabase db,String table){Set<String>s=new HashSet<>();Cursor c=db.rawQuery("PRAGMA table_info("+table+")",null);try{while(c.moveToNext())s.add(c.getString(c.getColumnIndexOrThrow("name")));}finally{c.close();}return s;}
    private static void put(ContentValues v,String k,Object x){if(x instanceof Boolean)v.put(k,(Boolean)x?1:0);else if(x instanceof Integer)v.put(k,(Integer)x);else if(x instanceof Long)v.put(k,(Long)x);else if(x instanceof Number)v.put(k,((Number)x).doubleValue());else v.put(k,String.valueOf(x));}

    private static void writeZip(Context c,byte[] json,byte[] diag)throws Exception{
        if(Build.VERSION.SDK_INT>=29)writeZipMediaStore(c,json,diag);else writeZipLegacy(json,diag);
    }
    private static void writeEntries(OutputStream raw,byte[] json,byte[] diag)throws Exception{try(ZipOutputStream z=new ZipOutputStream(new BufferedOutputStream(raw))){z.putNextEntry(new ZipEntry("backup.json"));z.write(json);z.closeEntry();z.putNextEntry(new ZipEntry("diagnostics.txt"));z.write(diag);z.closeEntry();}}
    private static void writeZipLegacy(byte[] json,byte[] diag)throws Exception{File dir=Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS);if(!dir.exists()&&!dir.mkdirs())throw new IllegalStateException("Cannot create Downloads");File tmp=new File(dir,TEMP_NAME),dst=new File(dir,FILE_NAME);try(FileOutputStream f=new FileOutputStream(tmp)){writeEntries(f,json,diag);}if(dst.exists()&&!dst.delete())throw new IllegalStateException("Cannot replace old backup");if(!tmp.renameTo(dst))throw new IllegalStateException("Cannot finalize backup file");}
    private static void writeZipMediaStore(Context c,byte[] json,byte[] diag)throws Exception{ContentResolver r=c.getContentResolver();Uri collection=MediaStore.Downloads.EXTERNAL_CONTENT_URI;deleteByName(r,collection,TEMP_NAME);ContentValues v=new ContentValues();v.put(MediaStore.MediaColumns.DISPLAY_NAME,TEMP_NAME);v.put(MediaStore.MediaColumns.MIME_TYPE,"application/zip");v.put(MediaStore.MediaColumns.RELATIVE_PATH,Environment.DIRECTORY_DOWNLOADS+"/");v.put(MediaStore.MediaColumns.IS_PENDING,1);Uri tmp=r.insert(collection,v);if(tmp==null)throw new IllegalStateException("Cannot create Downloads backup");boolean ok=false;try(OutputStream o=r.openOutputStream(tmp,"w")){if(o==null)throw new IllegalStateException("Cannot open Downloads output");writeEntries(o,json,diag);ok=true;}finally{if(!ok)r.delete(tmp,null,null);}deleteByName(r,collection,FILE_NAME);ContentValues done=new ContentValues();done.put(MediaStore.MediaColumns.DISPLAY_NAME,FILE_NAME);done.put(MediaStore.MediaColumns.IS_PENDING,0);if(r.update(tmp,done,null,null)<=0)throw new IllegalStateException("Cannot finalize Downloads backup");}
    private static void deleteByName(ContentResolver r,Uri collection,String name){Cursor c=r.query(collection,new String[]{MediaStore.MediaColumns._ID},MediaStore.MediaColumns.DISPLAY_NAME+"=?",new String[]{name},null);if(c==null)return;try{while(c.moveToNext())r.delete(ContentUris.withAppendedId(collection,c.getLong(0)),null,null);}finally{c.close();}}

    private static boolean backupExists(Context c)throws Exception{InputStream in=openBackup(c);if(in==null)return false;in.close();return true;}
    private static byte[] readZipEntry(Context c,String wanted)throws Exception{InputStream raw=openBackup(c);if(raw==null)throw new IllegalStateException("Backup not found in Downloads");try(ZipInputStream z=new ZipInputStream(new BufferedInputStream(raw))){ZipEntry e;byte[] buf=new byte[8192];while((e=z.getNextEntry())!=null){if(!wanted.equals(e.getName()))continue;ByteArrayOutputStream b=new ByteArrayOutputStream();int n;while((n=z.read(buf))>0)b.write(buf,0,n);return b.toByteArray();}}return null;}
    private static InputStream openBackup(Context c)throws Exception{if(Build.VERSION.SDK_INT<29){File f=new File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS),FILE_NAME);return f.exists()?new FileInputStream(f):null;}ContentResolver r=c.getContentResolver();Uri collection=MediaStore.Downloads.EXTERNAL_CONTENT_URI;Cursor cur=r.query(collection,new String[]{MediaStore.MediaColumns._ID},MediaStore.MediaColumns.DISPLAY_NAME+"=?",new String[]{FILE_NAME},MediaStore.MediaColumns.DATE_MODIFIED+" DESC");if(cur==null)return null;try{if(!cur.moveToFirst())return null;Uri u=ContentUris.withAppendedId(collection,cur.getLong(0));return r.openInputStream(u);}finally{cur.close();}}
    private static String shortMsg(Exception e){String s=e.getMessage();if(s==null)s=e.getClass().getSimpleName();return s.length()>220?s.substring(0,220):s;}
}
