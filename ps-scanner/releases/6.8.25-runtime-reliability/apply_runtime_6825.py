#!/usr/bin/env python3
from __future__ import annotations
import argparse,ast,datetime as dt,os,py_compile,re,tarfile
from pathlib import Path

RELEASE="6.8.25"; PREVIOUS="6.8.24"
MAIN_MARKER="V6825_RUNTIME_ENDPOINTS_AND_MONITOR"
HISTORY_MARKER="V6825_ADAPTIVE_HISTORY_PRESSURE_PACING"
RUNTIME_MARKER="V6825_RUNTIME_RELIABILITY_AND_DATA_QUALITY_PASSIVE"
UI_MARKER="PS_RUNTIME_RELIABILITY_V6825"
HERE=Path(__file__).resolve().parent

def fail(msg): raise RuntimeError(msg)
def read(p):
    if not p.exists(): fail("missing required file: "+str(p))
    return p.read_text()
def version_of(text):
    m=re.search(r'(?m)^\s*VERSION\s*=\s*["\']([^"\']+)["\']',text)
    return m.group(1) if m else ""
def compile_text(name,text): compile(text,name,"exec")

def patch_version(text):
    v=version_of(text)
    if v==RELEASE:return text
    if v!=PREVIOUS:fail("expected VERSION 6.8.24 (or already 6.8.25), found "+(v or "UNKNOWN"))
    out,n=re.subn(r'(?m)^(\s*VERSION\s*=\s*)["\']6\.8\.24["\']\s*$',r'\1"6.8.25"',text,count=1)
    if n!=1:fail("VERSION assignment not uniquely patchable")
    return out

def patch_history(text):
    if HISTORY_MARKER in text:return text
    names={n.name for n in ast.walk(ast.parse(text)) if isinstance(n,ast.FunctionDef)}
    if not {"wait_for_slot","record_rate_limit","record_success","status","status_cached"}.issubset(names):
        fail("history_control.py missing expected pacing functions")
    if "_GLOBAL_COOLDOWN_UNTIL" not in text or "_CONSECUTIVE_429" not in text:
        fail("history_control.py pacing globals missing")
    if "_LAST_429_WALL" not in text:
        m=re.search(r'(?m)^_CONSECUTIVE_429\s*=\s*0\s*$',text)
        if not m:fail("_CONSECUTIVE_429 anchor missing")
        text=text[:m.end()]+"\n_LAST_429_WALL = 0.0\n"+text[m.end():]
    block=re.search(r'(?ms)^def wait_for_slot\(\).*?(?=^def record_rate_limit\()',text)
    if not block:fail("wait_for_slot block missing")
    replacement='''# V6825_ADAPTIVE_HISTORY_PRESSURE_PACING
def _adaptive_history_min_gap(settings: Dict[str, Any]) -> float:
    base=max(0.25,float(settings.get("history_min_request_interval_seconds",1.25)))
    pressure=1.0
    if _CONSECUTIVE_429>0:
        pressure=max(pressure,1.0+0.5*min(4,int(_CONSECUTIVE_429)))
    if _LAST_429_WALL:
        age=max(0.0,time.time()-_LAST_429_WALL)
        if age<300.0:pressure=max(pressure,2.0)
        elif age<900.0:pressure=max(pressure,1.5)
    return min(8.0,base*pressure)

def wait_for_slot() -> float:
    """Historical-candle-only adaptive post-429 pressure pacing."""
    global _LAST_REQUEST_MONO
    settings=load_settings()
    min_gap=_adaptive_history_min_gap(settings)
    with _LOCK:
        now_wall=time.time();now_mono=time.monotonic()
        wait=max(0.0,_GLOBAL_COOLDOWN_UNTIL-now_wall,min_gap-(now_mono-_LAST_REQUEST_MONO))
        if wait>0:time.sleep(wait)
        _LAST_REQUEST_MONO=time.monotonic()
        return wait

'''
    text=text[:block.start()]+replacement+text[block.end():]
    text,n=re.subn(r'(?m)^(\s*)global _GLOBAL_COOLDOWN_UNTIL, _CONSECUTIVE_429\s*$',
                   r'\1global _GLOBAL_COOLDOWN_UNTIL, _CONSECUTIVE_429, _LAST_429_WALL',text,count=1)
    if n!=1:fail("record_rate_limit global declaration not uniquely patchable")
    text,n=re.subn(r'(?m)^(\s*)_CONSECUTIVE_429 \+= 1\s*$',
                   r'\1_CONSECUTIVE_429 += 1\n\1_LAST_429_WALL = time.time()',text,count=1)
    if n!=1:fail("record_rate_limit increment not uniquely patchable")
    needle='"minimum_request_interval_seconds": float(settings.get("history_min_request_interval_seconds", 1.25)),'
    if needle in text and '"effective_request_interval_seconds"' not in text:
        text=text.replace(needle,needle+'\n            "effective_request_interval_seconds": round(_adaptive_history_min_gap(settings),3),',1)
    compile_text("history_control.py",text); return text

def patch_main(text):
    if MAIN_MARKER in text:return text
    ast.parse(text)
    if "app=FastAPI(" not in text.replace(" ",""):fail("main.py FastAPI app assignment missing")
    if 'app.mount("/static"' not in text and "app.mount('/static'" not in text:
        fail("main.py /static mount missing; apply 6.8.24 Static Assets Hotfix v2 first")
    addition='''

# V6825_RUNTIME_ENDPOINTS_AND_MONITOR
from . import runtime_reliability as _runtime_reliability_6825

@app.on_event("startup")
def _runtime_reliability_6825_startup():
    _runtime_reliability_6825.start()

@app.on_event("shutdown")
def _runtime_reliability_6825_shutdown():
    _runtime_reliability_6825.stop()

@app.get("/api/runtime/reliability")
def runtime_reliability_6825_status():
    return _runtime_reliability_6825.status_cached()

@app.get("/api/data-quality")
def runtime_data_quality_6825_status():
    return _runtime_reliability_6825.data_quality_cached()

@app.get("/api/runtime/session-ledger")
def runtime_session_ledger_6825(limit: int = 14):
    return {"rows":_runtime_reliability_6825.session_ledger(limit=max(1,min(90,int(limit))))}
'''
    out=text.rstrip()+addition+"\n"; compile_text("main.py",out); return out

def patch_index(text):
    css='<link rel="stylesheet" href="/static/ps_runtime_6825.css?v=6825">'
    js='<script defer src="/static/ps_runtime_6825.js?v=6825"></script>'
    if css not in text:
        if "</head>" not in text:fail("index.html </head> missing")
        text=text.replace("</head>","  "+css+"\n</head>",1)
    if js not in text:
        if "</body>" not in text:fail("index.html </body> missing")
        text=text.replace("</body>","  "+js+"\n</body>",1)
    return text

def make_backup(root,paths):
    stamp=dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    d=root/"data"/"hotfix_backups";d.mkdir(parents=True,exist_ok=True)
    p=d/("psscanner-6.8.25-runtime-"+stamp+".tar.gz")
    with tarfile.open(p,"w:gz") as t:
        for x in paths:
            if x.exists():t.add(x,arcname=str(x.relative_to(root)))
    return p

def main():
    ap=argparse.ArgumentParser(description="PS Scanner 6.8.25 Runtime Reliability installer")
    ap.add_argument("--app-root",default=str(Path.home()/"Applications"/"PS_Scanner_Final"))
    ap.add_argument("--dry-run",action="store_true")
    a=ap.parse_args()
    root=Path(a.app_root).expanduser().resolve(); q=root/"psscanner_quant"; static=root/"static"; scripts=root/"scripts"
    p={"constants":q/"constants.py","main":q/"main.py","history":q/"history_control.py",
       "book_policy":q/"book_policy.py","orders":q/"orders.py","runtime":q/"runtime_reliability.py",
       "index":static/"index.html","js":static/"ps_runtime_6825.js","css":static/"ps_runtime_6825.css",
       "exporter":scripts/"export_support_6825.py"}
    runtime=read(HERE/"runtime_reliability.py.payload"); js=read(HERE/"ps_runtime_6825.js.payload")
    css=read(HERE/"ps_runtime_6825.css.payload"); exporter=read(HERE/"export_support_6825.py.payload")
    if RUNTIME_MARKER not in runtime:fail("runtime payload marker missing")
    if UI_MARKER not in js or UI_MARKER not in css:fail("UI payload marker missing")
    compile_text("runtime_reliability.py",runtime);compile_text("export_support_6825.py",exporter)

    constants=read(p["constants"]);v=version_of(constants)
    if v not in (PREVIOUS,RELEASE):fail("expected installed 6.8.24 or 6.8.25, found "+(v or "UNKNOWN"))
    if v==PREVIOUS:
        if "V6824_CANONICAL_BOOK_EXECUTION_AND_PRESENTATION_POLICY" not in read(p["book_policy"]):
            fail("6.8.24 canonical book-policy marker missing")
        if "V6824_PREVIEW_PRICE_DRIFT_REVALIDATION" not in read(p["orders"]):
            fail("6.8.24 preview price-drift marker missing")
    constants_new=patch_version(constants);main_new=patch_main(read(p["main"]))
    history_new=patch_history(read(p["history"]));index_new=patch_index(read(p["index"]))
    for name,text in (("constants.py",constants_new),("main.py",main_new),("history_control.py",history_new)):
        compile_text(name,text)

    targets=[p["constants"],p["main"],p["history"],p["runtime"],p["index"],p["js"],p["css"],p["exporter"]]
    print("PS_SCANNER_6_8_25_RUNTIME_RELIABILITY");print("App root:",root);print("Installed version:",v)
    print("Safety: execution, Static IP, market hours, reconciliation, order risk, qualification and freshness gates remain unchanged.")
    if a.dry_run:
        print("DRY-RUN PASS: structural anchors and Python payloads validated; no files changed.");return

    originals={x:(x.read_bytes() if x.exists() else None) for x in targets};b=make_backup(root,targets);print("Backup:",b)
    try:
        scripts.mkdir(parents=True,exist_ok=True)
        p["constants"].write_text(constants_new);p["main"].write_text(main_new);p["history"].write_text(history_new)
        p["runtime"].write_text(runtime);p["index"].write_text(index_new);p["js"].write_text(js);p["css"].write_text(css);p["exporter"].write_text(exporter)
        try:os.chmod(p["exporter"],0o755)
        except Exception:pass
        for x in (p["constants"],p["main"],p["history"],p["runtime"],p["exporter"]):py_compile.compile(str(x),doraise=True)
        if version_of(read(p["constants"]))!=RELEASE:fail("post-write version check failed")
        if MAIN_MARKER not in read(p["main"]) or HISTORY_MARKER not in read(p["history"]) or RUNTIME_MARKER not in read(p["runtime"]):
            fail("post-write marker verification failed")
        if "V6824_CANONICAL_BOOK_EXECUTION_AND_PRESENTATION_POLICY" not in read(p["book_policy"]):fail("book-policy marker unexpectedly lost")
        if "V6824_PREVIEW_PRICE_DRIFT_REVALIDATION" not in read(p["orders"]):fail("preview-drift marker unexpectedly lost")
        print("APPLY PASS: PS Scanner 6.8.25 installed.");print("Restart backend once, then run ./verify_6825.sh")
    except Exception:
        for x,data in originals.items():
            try:
                if data is None:
                    if x.exists():x.unlink()
                else:x.parent.mkdir(parents=True,exist_ok=True);x.write_bytes(data)
            except Exception:pass
        raise

if __name__=="__main__":main()
