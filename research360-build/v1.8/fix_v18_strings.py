from pathlib import Path
import re
p=Path('/tmp/r360/app/src/main/java/com/suhas/research360engine/MainActivity.java')
s=p.read_text()
# re.sub replacement strings interpret backslashes; normalize the two v1.8 multiline Java literals explicitly.
pat=r'gate\.setText\(Db\.get\(this\)\.r360TodayPipeline\(\)\+String\.format\(Locale\.US,"\s*Evidence: %d resolved shadow • %\.1f%% ₹100-net wins • ₹%\.0f cumulative net",s\.r360ShadowTrades,s\.r360WinRate\(\)\*100,s\.r360ShadowNet\)\);'
rep='gate.setText(Db.get(this).r360TodayPipeline()+String.format(Locale.US,"\\nEvidence: %d resolved shadow • %.1f%% ₹100-net wins • ₹%.0f cumulative net",s.r360ShadowTrades,s.r360WinRate()*100,s.r360ShadowNet));'
s,n=re.subn(pat,lambda m:rep,s,count=1,flags=re.S)
if n!=1: raise SystemExit('gate literal fix failed')
pat=r'stats\.setText\(String\.format\(Locale\.US,"Validated R360 stock messages: %d\s*Parsed R360 signals: %d • resolved observations: %d\s*Qualified R360 shadow trades: %d • %d ₹100-net wins • ₹%\.2f\s*R360 confidence: %d%% • evidence maturity: %d%%\s*Live net today: ₹%\.2f\s*Budget: ₹%\.0f • Daily loss ceiling: ₹%\.0f\s*WATCH/rejected calls remain internal and do not appear as recommendations\.",s\.notifications,s\.parsed,s\.resolvedSignals,s\.r360ShadowTrades,s\.r360ShadowWins,s\.r360ShadowNet,s\.r360Confidence\(\),s\.r360Maturity\(\),s\.liveNetToday,AppState\.budget\(this\),AppState\.dailyLossLimit\(this\)\)\);'
rep='stats.setText(String.format(Locale.US,"Validated R360 stock messages: %d\\nParsed R360 signals: %d • resolved observations: %d\\nQualified R360 shadow trades: %d • %d ₹100-net wins • ₹%.2f\\nR360 confidence: %d%% • evidence maturity: %d%%\\nLive net today: ₹%.2f\\nBudget: ₹%.0f • Daily loss ceiling: ₹%.0f\\nWATCH/rejected calls remain internal and do not appear as recommendations.",s.notifications,s.parsed,s.resolvedSignals,s.r360ShadowTrades,s.r360ShadowWins,s.r360ShadowNet,s.r360Confidence(),s.r360Maturity(),s.liveNetToday,AppState.budget(this),AppState.dailyLossLimit(this)));'
s,n2=re.subn(pat,lambda m:rep,s,count=1,flags=re.S)
if n2!=1: raise SystemExit('stats literal fix failed')
p.write_text(s)
print('v1.8 Java strings fixed')
