#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import plistlib
import re
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

if len(sys.argv) != 3:
    print("usage: migrate_groww_secrets.py OLD_APP OUTPUT", file=sys.stderr)
    raise SystemExit(2)

OLD_APP = Path(sys.argv[1]).expanduser().resolve()
OUT = Path(sys.argv[2]).expanduser()
HOME = Path.home()
BASE = "https://api.groww.in"

if not OLD_APP.exists():
    print("OLD_APP_NOT_FOUND", file=sys.stderr)
    raise SystemExit(3)

BAD_VALUES = {
    "", "none", "null", "changeme", "your_api_key", "your_secret", "your_token",
    "api_key", "api_secret", "access_token", "token", "secret", "placeholder",
}

ALIASES = {
    "api_key": {
        "growwapikey", "apikey", "userapikey", "clientapikey", "clientkey",
    },
    "api_secret": {
        "growwapisecret", "apisecret", "userapisecret", "growwsecret",
        "clientsecret", "secretkey",
    },
    "totp_token": {
        "growwtotptoken", "totptoken", "growwapitoken", "apitoken",
    },
    "totp_secret": {
        "growwtotpsecret", "totpsecret", "totpseed", "totpkey",
        "growwtotpseed",
    },
    "access_token": {
        "growwaccesstoken", "accesstoken", "apiauthtoken", "authtoken",
        "bearertoken", "sessiontoken",
    },
    "unknown_token": {"growwtoken", "token"},
}


def nk(s: object) -> str:
    return "".join(c for c in str(s).lower() if c.isalnum())


def plausible(v: object) -> bool:
    s = str(v or "").strip().strip('"\'')
    return bool(s and s.lower() not in BAD_VALUES and len(s) >= 6)


def flatten(obj: object, out: Dict[str, str], prefix: str = "") -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}{k}"
            if isinstance(v, (dict, list)):
                flatten(v, out, key + ".")
            elif isinstance(v, (str, int, float)) and plausible(v):
                out[key] = str(v).strip()
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            flatten(v, out, f"{prefix}{i}.")


def path_relevant(p: Path) -> bool:
    s = str(p).lower().replace(" ", "")
    return any(x in s for x in ("groww", "psscanner", "ps_scanner", "ps-scanner"))


def parse_text_file(p: Path) -> Dict[str, str]:
    try:
        if p.stat().st_size > 2 * 1024 * 1024:
            return {}
        raw = p.read_bytes()
        if b"\x00" in raw[:4096]:
            return {}
        text = raw.decode("utf-8", errors="ignore")
    except Exception:
        return {}

    vals: Dict[str, str] = {}
    try:
        flatten(json.loads(text), vals)
    except Exception:
        pass
    try:
        flatten(plistlib.loads(raw), vals)
    except Exception:
        pass

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        m = re.match(
            r"(?:export\s+)?([A-Za-z_][A-Za-z0-9_.-]*)\s*(?:=|:)\s*[rRuUbBfF]*([\"\']?)(.*?)\2\s*(?:#.*)?$",
            line,
        )
        if m:
            k, v = m.group(1), m.group(3).strip()
            if plausible(v):
                vals.setdefault(k, v)

    stripped = text.strip()
    if "\n" not in stripped and plausible(stripped) and len(stripped) <= 16384:
        bn = nk(p.stem)
        if "totp" in bn and ("token" in bn or "api" in bn) and "secret" not in bn:
            vals.setdefault("totp_token", stripped)
        elif "totp" in bn:
            vals.setdefault("totp_secret", stripped)
        elif "secret" in bn:
            vals.setdefault("api_secret", stripped)
        elif "access" in bn or "auth" in bn or "bearer" in bn:
            vals.setdefault("access_token", stripped)
        elif "apikey" in bn:
            vals.setdefault("api_key", stripped)
        elif "apitoken" in bn:
            vals.setdefault("totp_token", stripped)
        elif "growwtoken" in bn or bn == "token":
            vals.setdefault("unknown_token", stripped)
    return vals


def canonical_from(vals: Dict[str, str], *, relevant_path: bool = True) -> Dict[str, str]:
    norm = {nk(k): v for k, v in vals.items() if plausible(v)}
    out: Dict[str, str] = {}
    for ck, aliases in ALIASES.items():
        for key, value in norm.items():
            if key in aliases or any(key.endswith(a) for a in aliases):
                out.setdefault(ck, value)
                break
    if relevant_path:
        if "api_secret" not in out and "secret" in norm and plausible(norm["secret"]):
            out["api_secret"] = norm["secret"]
        if "api_key" not in out and "key" in norm and plausible(norm["key"]):
            out["api_key"] = norm["key"]
        if "unknown_token" not in out and "token" in norm and plausible(norm["token"]):
            out["unknown_token"] = norm["token"]
    return out


def walk_limited(root: Path, max_depth: int) -> Iterable[Path]:
    if not root.exists():
        return
    base_depth = len(root.parts)
    for cur, dirs, files in os.walk(root, topdown=True):
        cp = Path(cur)
        depth = len(cp.parts) - base_depth
        dirs[:] = [d for d in dirs if not d.startswith(".") or d.lower() in (
            ".config", ".psscanner", ".ps_scanner", ".groww"
        )]
        if depth >= max_depth:
            dirs[:] = []
        for name in files:
            yield cp / name


def candidate_files() -> List[Path]:
    seen = set()
    out: List[Path] = []
    def add(p: Path) -> None:
        try:
            rp = p.expanduser().resolve()
        except Exception:
            return
        if rp in seen or not rp.is_file():
            return
        seen.add(rp); out.append(rp)

    for p in walk_limited(OLD_APP, 8):
        add(p)
    for root in [
        HOME / ".config", HOME / ".psscanner", HOME / ".ps_scanner", HOME / ".groww",
        HOME / "Library" / "Application Support", HOME / "Library" / "Preferences",
        HOME / "Library" / "LaunchAgents",
    ]:
        for p in walk_limited(root, 4):
            if path_relevant(p):
                add(p)
    try:
        for p in HOME.iterdir():
            if p.is_file() and path_relevant(p):
                add(p)
    except Exception:
        pass
    return out


def launchd_bundle() -> Optional[Tuple[str, Dict[str, str]]]:
    vals: Dict[str, str] = {}
    plist = HOME / "Library" / "LaunchAgents" / "com.psscanner.final.plist"
    if plist.exists():
        try:
            obj = plistlib.loads(plist.read_bytes())
            env = obj.get("EnvironmentVariables") if isinstance(obj, dict) else None
            if isinstance(env, dict):
                vals.update({str(k): str(v) for k, v in env.items() if plausible(v)})
        except Exception:
            pass
    for name in [
        "GROWW_API_KEY", "GROWW_API_SECRET", "GROWW_TOTP_TOKEN", "GROWW_TOTP_SECRET",
        "GROWW_TOTP", "GROWW_ACCESS_TOKEN", "GROWW_API_TOKEN", "API_AUTH_TOKEN",
    ]:
        try:
            r = subprocess.run(["launchctl", "getenv", name], capture_output=True, text=True, timeout=2)
            if plausible(r.stdout.strip()):
                vals[name] = r.stdout.strip()
        except Exception:
            pass
    c = canonical_from(vals, relevant_path=True)
    return ("launchd_environment", c) if c else None


def http_json(url: str, *, method: str = "GET", headers: Optional[dict] = None, body: Optional[dict] = None, timeout: float = 8.0) -> dict:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    obj = json.loads(raw.decode("utf-8", errors="replace"))
    return obj if isinstance(obj, dict) else {"payload": obj}


def profile_ok(token: str) -> bool:
    if not plausible(token):
        return False
    try:
        obj = http_json(
            BASE + "/v1/user/detail",
            headers={"Accept":"application/json", "Authorization":f"Bearer {token}", "X-API-VERSION":"1.0"},
        )
        if str(obj.get("status") or "SUCCESS").upper() == "FAILURE":
            return False
        payload = obj.get("payload", obj)
        return isinstance(payload, dict) and bool(payload.get("ucc") or payload.get("vendor_user_id") or payload.get("active_segments") is not None)
    except Exception:
        return False


def approval_token(api_key: str, api_secret: str) -> Optional[str]:
    try:
        ts = str(int(time.time()))
        checksum = hashlib.sha256((api_secret + ts).encode("utf-8")).hexdigest()
        obj = http_json(
            BASE + "/v1/token/api/access", method="POST",
            headers={"Authorization":f"Bearer {api_key}", "Content-Type":"application/json", "Accept":"application/json"},
            body={"key_type":"approval", "checksum":checksum, "timestamp":ts},
        )
        tok = obj.get("token") or (obj.get("payload") or {}).get("token")
        return str(tok).strip() if plausible(tok) else None
    except Exception:
        return None


def totp_code(secret: str) -> str:
    cleaned = re.sub(r"\s+", "", secret).upper()
    cleaned += "=" * ((8 - len(cleaned) % 8) % 8)
    key = base64.b32decode(cleaned, casefold=True)
    counter = int(time.time() // 30)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    off = digest[-1] & 0x0F
    num = (struct.unpack(">I", digest[off:off+4])[0] & 0x7FFFFFFF) % 1_000_000
    return f"{num:06d}"


def totp_access_token(totp_token: str, totp_secret: str) -> Optional[str]:
    try:
        obj = http_json(
            BASE + "/v1/token/api/access", method="POST",
            headers={"Authorization":f"Bearer {totp_token}", "Content-Type":"application/json", "Accept":"application/json"},
            body={"key_type":"totp", "totp":totp_code(totp_secret)},
        )
        tok = obj.get("token") or (obj.get("payload") or {}).get("token")
        return str(tok).strip() if plausible(tok) else None
    except Exception:
        return None


files = candidate_files()
files.sort(key=lambda p: (
    0 if path_relevant(p) else 1,
    0 if any(w in p.name.lower() for w in ("credential", "auth", "groww", "secret", "token", ".env")) else 1,
    len(str(p)),
))

bundles: List[Tuple[str, Path, Dict[str, str]]] = []
for p in files:
    vals = parse_text_file(p)
    if not vals:
        continue
    c = canonical_from(vals, relevant_path=path_relevant(p))
    if c:
        bundles.append((str(p), p.parent, c))

ld = launchd_bundle()
if ld:
    bundles.append((ld[0], Path("/"), ld[1]))

envvals = {k: os.environ[k] for k in (
    "GROWW_API_KEY", "GROWW_API_SECRET", "GROWW_TOTP_TOKEN", "GROWW_TOTP_SECRET",
    "GROWW_TOTP", "GROWW_ACCESS_TOKEN", "GROWW_API_TOKEN", "API_AUTH_TOKEN",
) if plausible(os.environ.get(k))}
if envvals:
    bundles.append(("installer_environment", Path("/"), canonical_from(envvals, relevant_path=True)))

if not bundles:
    print("NO_GROWW_CREDENTIALS_FOUND", file=sys.stderr)
    raise SystemExit(4)

# 1) Validate access-token candidates without generating any new token.
valid_access: Optional[Tuple[str, str, Dict[str, str], Path]] = None
seen_tokens = set()
for source, parent, b in bundles:
    for field in ("access_token", "unknown_token"):
        tok = b.get(field)
        if not tok or tok in seen_tokens:
            continue
        seen_tokens.add(tok)
        if profile_ok(tok):
            valid_access = (tok, source, b, parent)
            break
    if valid_access:
        break

# Build refresh pairs. Same-file pairs first, then same-directory pairs, then a very small
# cross-source fallback. This prevents the v6.0.1 bug that merged unrelated secrets.
approval_pairs: List[Tuple[str, str, str]] = []
totp_pairs: List[Tuple[str, str, str]] = []

def add_unique(lst, item):
    sig = item[:2]
    if all(x[:2] != sig for x in lst):
        lst.append(item)

for source, parent, b in bundles:
    if b.get("api_key") and b.get("api_secret"):
        add_unique(approval_pairs, (b["api_key"], b["api_secret"], source))
    tt = b.get("totp_token")
    if not tt and b.get("totp_secret") and not b.get("api_secret"):
        tt = b.get("api_key")
    if tt and b.get("totp_secret"):
        add_unique(totp_pairs, (tt, b["totp_secret"], source))

# Same-directory complements.
for source, parent, b in bundles:
    same = [x for x in bundles if x[1] == parent]
    if b.get("api_key"):
        for s2, _, b2 in same:
            if b2.get("api_secret"):
                add_unique(approval_pairs, (b["api_key"], b2["api_secret"], source + " + " + s2))
    token = b.get("totp_token") or (b.get("api_key") if b.get("totp_secret") and not b.get("api_secret") else None)
    if token:
        for s2, _, b2 in same:
            if b2.get("totp_secret"):
                add_unique(totp_pairs, (token, b2["totp_secret"], source + " + " + s2))

# Small global fallback, capped so we do not burn authentication rate limits.
keys = [(s,b.get("api_key")) for s,_,b in bundles if b.get("api_key")]
secs = [(s,b.get("api_secret")) for s,_,b in bundles if b.get("api_secret")]
for ks,k in keys[:4]:
    for ss,s in secs[:4]:
        add_unique(approval_pairs, (k,s,ks + " + " + ss))

tokens = [(s,b.get("totp_token")) for s,_,b in bundles if b.get("totp_token")]
tsecs = [(s,b.get("totp_secret")) for s,_,b in bundles if b.get("totp_secret")]
for ts,t in tokens[:4]:
    for ss,s in tsecs[:4]:
        add_unique(totp_pairs, (t,s,ts + " + " + ss))

chosen: Dict[str, str] = {}
chosen_source = ""
auth_mode = ""

# Prefer approval flow when it validates: unlike v6.0.1 we never let the mere presence
# of a TOTP secret override a valid API-key+secret pair.
for api_key, api_secret, source in approval_pairs[:8]:
    tok = approval_token(api_key, api_secret)
    if tok and profile_ok(tok):
        chosen = {"api_key":api_key, "api_secret":api_secret, "access_token":tok}
        chosen_source = source
        auth_mode = "approval"
        break

if not chosen:
    for tt, ts, source in totp_pairs[:8]:
        tok = totp_access_token(tt, ts)
        if tok and profile_ok(tok):
            chosen = {"totp_token":tt, "totp_secret":ts, "access_token":tok}
            chosen_source = source
            auth_mode = "totp"
            break

if not chosen and valid_access:
    tok, source, b, _ = valid_access
    chosen = {"access_token":tok}
    chosen_source = source
    auth_mode = "access_token"

if not chosen:
    print("GROWW_CREDENTIALS_FOUND_BUT_NONE_AUTHENTICATED", file=sys.stderr)
    print("Old files were not modified; secret values were never printed.", file=sys.stderr)
    print("Candidate credential bundles inspected:", len(bundles), file=sys.stderr)
    raise SystemExit(5)

payload = {
    "migrated_from": "PS_Scanner_Final",
    "migration_source": chosen_source,
    "auth_mode": auth_mode,
    "validated_at_epoch": int(time.time()),
    **chosen,
}
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(payload, indent=2))
os.chmod(OUT, 0o600)

print("GROWW_CREDENTIALS_MIGRATED_AND_VALIDATED")
print("auth_mode=" + auth_mode)
print("refresh_capable=" + ("yes" if auth_mode in ("approval","totp") else "no"))
print("capabilities=" + ",".join(k for k in ("api_key","api_secret","totp_token","totp_secret","access_token") if payload.get(k)))
print("candidate_bundles=" + str(len(bundles)))
