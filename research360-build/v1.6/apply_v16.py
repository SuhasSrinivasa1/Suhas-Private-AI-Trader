from pathlib import Path
import re

root=Path('/tmp/r360')

# ---------- build version ----------
p=root/'app/build.gradle'
s=p.read_text()
s=re.sub(r"versionCode\s+\d+","versionCode 160",s,count=1)
s=re.sub(r"versionName\s+'[^']+'","versionName '1.6.0'",s,count=1)
p.write_text(s)

# ---------- copy LearningBackup ----------
src=Path.cwd()/'research360-build/v1.6/LearningBackup.java'
if not src.exists(): raise SystemExit('LearningBackup.java missing')
dst=root/'app/src/main/java/com/suhas/research360engine/LearningBackup.java'
bs=src.read_text()
# MediaStore.Downloads/RELATIVE_PATH/IS_PENDING are API 29+, and these methods are called only
# behind explicit SDK_INT >=29 branches. TargetApi tells Android Lint about that runtime gate.
bs=bs.replace('    private static void writeZipMediaStore(Context c,byte[] json,byte[] diag)throws Exception{','    @android.annotation.TargetApi(29)\n    private static void writeZipMediaStore(Context c,byte[] json,byte[] diag)throws Exception{',1)
bs=bs.replace('    private static InputStream openBackup(Context c)throws Exception{','    @android.annotation.TargetApi(29)\n    private static InputStream openBackup(Context c)throws Exception{',1)
dst.write_text(bs)

# ---------- manifest: legacy Downloads permission for LG G7 Android 8/9 ----------
p=root/'app/src/main/AndroidManifest.xml'
s=p.read_text()
if 'android.permission.WRITE_EXTERNAL_STORAGE' not in s:
    app=s.find('<application')
    if app<0: raise SystemExit('manifest application marker missing')
    perms='    <uses-permission android:name="android.permission.WRITE_EXTERNAL_STORAGE" android:maxSdkVersion="28" />\n    <uses-permission android:name="android.permission.READ_EXTERNAL_STORAGE" android:maxSdkVersion="28" />\n'
    s=s[:app]+perms+s[app:]
p.write_text(s)

# ---------- EngineService: auto-restore on fresh install + rolling checkpoints ----------
p=root/'app/src/main/java/com/suhas/research360engine/EngineService.java'
s=p.read_text()
if 'LearningBackup.autoRestoreIfFresh(this)' not in s:
    s,n=re.subn(r'(super\.onCreate\(\);\s*)',r'\1LearningBackup.autoRestoreIfFresh(this); ',s,count=1)
    if n!=1: raise SystemExit('EngineService super.onCreate marker missing')
if 'LearningBackup.maybeBackup(this)' not in s:
    s,n=re.subn(r'runningTick\.set\(false\);',r'try{LearningBackup.maybeBackup(this);}catch(Exception ignored){}runningTick.set(false);',s,count=1)
    if n!=1: raise SystemExit('EngineService runningTick marker missing')
p.write_text(s)

# ---------- MainActivity: backup UI + permission + restore ----------
p=root/'app/src/main/java/com/suhas/research360engine/MainActivity.java'
s=p.read_text()
if 'backupStatus' not in s.split('private LinearLayout',1)[0]:
    s=s.replace('sectorSummary,sectorConfidence;','sectorSummary,sectorConfidence,backupStatus;',1)
    if 'backupStatus' not in s.split('private LinearLayout',1)[0]:
        s,n=re.subn(r'(private TextView [^;]+)(;)',r'\1,backupStatus\2',s,count=1)
        if n!=1: raise SystemExit('MainActivity TextView declaration marker missing')
s=s.replace('v1.5 • LG G7 ThinQ • validated R360 calls + independent model + all-positive-sector scanner',
            'v1.6 • LG G7 ThinQ • persistent learning backup + validated R360 + independent + positive-sector scanner',1)

if 'requestBackupStoragePermission();' not in s:
    s,n=re.subn(r'(buildUi\(\);\s*requestNotifications\(\);)',r'\1requestBackupStoragePermission();LearningBackup.autoRestoreIfFresh(this);',s,count=1)
    if n!=1: raise SystemExit('MainActivity buildUi/requestNotifications marker missing')

if 'PERSISTENT LEARNING BACKUP' not in s:
    marker='        LinearLayout access=card(root);access.addView(text("DEVICE ACCESS",13,MUTED,true));'
    backup='''        LinearLayout backup=card(root);backup.addView(text("PERSISTENT LEARNING BACKUP",13,MUTED,true));backup.addView(text("One rolling ZIP is kept in Downloads. It contains signals, market snapshots, shadow/live outcomes, sector learning, predictions and useful logs so the learning survives an uninstall. Groww API key, TOTP secret and access token are NEVER exported.",10,MUTED,false));backupStatus=text(LearningBackup.status(this),11,Color.WHITE,false);backup.addView(backupStatus);Button backupNow=button("BACKUP LEARNING NOW");backup.addView(backupNow);backupNow.setOnClickListener(v->{backupNow.setEnabled(false);new Thread(()->{LearningBackup.Result r=LearningBackup.backupNow(this,"MANUAL");runOnUiThread(()->{backupNow.setEnabled(true);Toast.makeText(this,r.message,Toast.LENGTH_LONG).show();refresh();});}).start();});Button restore=button("RESTORE LATEST BACKUP — EMPTY INSTALL ONLY");backup.addView(restore);restore.setOnClickListener(v->new AlertDialog.Builder(this).setTitle("Restore learning from Downloads?").setMessage("Restore is deliberately allowed only when this installation has no learning and no live trade. Existing/newer learning will never be overwritten. Groww credentials are not restored and must remain configured separately.").setNegativeButton("Cancel",null).setPositiveButton("RESTORE",(d,w)->{restore.setEnabled(false);new Thread(()->{LearningBackup.Result r=LearningBackup.restoreLatestIfFresh(this);runOnUiThread(()->{restore.setEnabled(true);Toast.makeText(this,r.message,Toast.LENGTH_LONG).show();refresh();});}).start();}).show());backup.addView(text("Automatic protection: a checkpoint is refreshed about every 15 minutes when learning changed, plus a final session backup after 15:35 IST. The same filename is replaced safely, so you only need to upload one file to ChatGPT.",10,MUTED,false));space(root,10);\n\n'''+marker
    if marker not in s: raise SystemExit('DEVICE ACCESS marker missing')
    s=s.replace(marker,backup,1)

if 'backupStatus.setText(LearningBackup.status(this))' not in s:
    marker='stats.setText(String.format(Locale.US,"Validated R360 stock messages:'
    idx=s.find(marker)
    if idx<0: raise SystemExit('stats refresh marker missing')
    s=s[:idx]+'if(backupStatus!=null)backupStatus.setText(LearningBackup.status(this));'+s[idx:]

if 'private void requestBackupStoragePermission()' not in s:
    marker='    private boolean marketOpen(){'
    methods='''    private void requestBackupStoragePermission(){if(Build.VERSION.SDK_INT<29&&(checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE)!=PackageManager.PERMISSION_GRANTED||checkSelfPermission(Manifest.permission.READ_EXTERNAL_STORAGE)!=PackageManager.PERMISSION_GRANTED))requestPermissions(new String[]{Manifest.permission.WRITE_EXTERNAL_STORAGE,Manifest.permission.READ_EXTERNAL_STORAGE},92);}\n    @Override public void onRequestPermissionsResult(int requestCode,String[] permissions,int[] grantResults){super.onRequestPermissionsResult(requestCode,permissions,grantResults);if(requestCode==92){boolean ok=true;for(int x:grantResults)if(x!=PackageManager.PERMISSION_GRANTED)ok=false;if(ok)new Thread(()->{LearningBackup.Result r=LearningBackup.autoRestoreIfFresh(this);runOnUiThread(()->{Toast.makeText(this,r.ok?r.message:"Downloads backup enabled",Toast.LENGTH_LONG).show();refresh();});}).start();else Toast.makeText(this,"Downloads permission is required to preserve learning across uninstall on this Android version",Toast.LENGTH_LONG).show();}}\n\n'''+marker
    if marker not in s: raise SystemExit('marketOpen marker missing')
    s=s.replace(marker,methods,1)
p.write_text(s)

checks=[
    (root/'app/build.gradle',"versionName '1.6.0'"),
    (root/'app/src/main/AndroidManifest.xml','WRITE_EXTERNAL_STORAGE'),
    (root/'app/src/main/java/com/suhas/research360engine/MainActivity.java','PERSISTENT LEARNING BACKUP'),
    (root/'app/src/main/java/com/suhas/research360engine/MainActivity.java','LearningBackup.backupNow'),
    (root/'app/src/main/java/com/suhas/research360engine/EngineService.java','LearningBackup.maybeBackup'),
    (root/'app/src/main/java/com/suhas/research360engine/EngineService.java','LearningBackup.autoRestoreIfFresh'),
    (root/'app/src/main/java/com/suhas/research360engine/LearningBackup.java','Research360-Intelligence-Learning-LATEST.zip'),
    (root/'app/src/main/java/com/suhas/research360engine/LearningBackup.java','@android.annotation.TargetApi(29)'),
]
for f,t in checks:
    if t not in f.read_text(): raise SystemExit(f'missing {t} in {f}')
print('v1.6 persistent backup patch applied')
