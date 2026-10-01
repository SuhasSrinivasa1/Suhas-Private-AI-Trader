from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import os
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests

from .config import load_settings
from .constants import GROWW_BASE_URL, IST, PUBLIC_IP_URL, TRADE_NOTIONAL_RUPEES, MAX_RUPEE_RISK_PER_TRADE
from .db import health, now_iso
from .paths import CREDENTIALS_PATH

_LOCK = RLock()


def _norm_key(k: str) -> str:
    return "".join(ch for ch in str(k).lower() if ch.isalnum())


def _flatten(obj: Any, out: Dict[str, Any]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            nk = _norm_key(k)
            if isinstance(v, (dict, list)):
                _flatten(v, out)
            elif isinstance(v, (str, int, float)) and v not in (None, ""):
                out.setdefault(nk, v)
    elif isinstance(obj, list):
        for v in obj:
            _flatten(v, out)


def _first(d: Dict[str, Any], names: Iterable[str]) -> Optional[str]:
    for n in names:
        v = d.get(_norm_key(n))
        if v not in (None, ""):
            return str(v).strip()
    return None


class GrowwBroker:
    def __init__(self) -> None:
        self._session = requests.Session()
        self._access_token: Optional[str] = None
        self._token_loaded_at = 0.0
        self._last_status: Dict[str, Any] = {}
        self._last_status_at = 0.0
        self._last_ip: Optional[str] = None
        self._last_ip_at = 0.0
        self._last_ltp_status: Dict[str, Any] = {}

    def _read_credentials(self) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        if not CREDENTIALS_PATH.exists():
            return {}, {}
        try:
            raw = json.loads(CREDENTIALS_PATH.read_text())
            flat: Dict[str, Any] = {}
            _flatten(raw, flat)
            return raw if isinstance(raw, dict) else {}, flat
        except Exception:
            return {}, {}

    def _write_credentials(self, raw: Dict[str, Any]) -> None:
        CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = CREDENTIALS_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(raw, indent=2, sort_keys=True))
        os.chmod(tmp, 0o600)
        os.replace(tmp, CREDENTIALS_PATH)
        os.chmod(CREDENTIALS_PATH, 0o600)

    def configured(self) -> bool:
        _, flat = self._read_credentials()
        return bool(_first(flat, ["access_token", "token", "api_key", "user_api_key", "groww_api_key"]))

    def credential_capabilities(self) -> Dict[str, bool]:
        _, flat = self._read_credentials()
        raw, _ = self._read_credentials()
        return {
            "access_token": bool(_first(flat, ["access_token", "token", "auth_token", "api_auth_token"])),
            "api_key": bool(_first(flat, ["api_key", "user_api_key", "groww_api_key"])),
            "api_secret": bool(_first(flat, ["api_secret", "secret", "groww_api_secret"])),
            "totp_token": bool(_first(flat, ["totp_token", "groww_totp_token"])),
            "totp_secret": bool(_first(flat, ["totp_secret", "totpseed", "totp_key"])),
            "auth_mode": str(raw.get("auth_mode") or "") if isinstance(raw, dict) else "",
        }

    def _token_from_file(self, flat: Dict[str, Any]) -> Optional[str]:
        return _first(flat, ["access_token", "auth_token", "api_auth_token", "token"])

    def _generate_token_api_secret(self, api_key: str, api_secret: str) -> str:
        ts = str(int(time.time()))
        checksum = hashlib.sha256((api_secret + ts).encode()).hexdigest()
        r = self._session.post(
            f"{GROWW_BASE_URL}/v1/token/api/access",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"key_type": "approval", "checksum": checksum, "timestamp": ts},
            timeout=12,
        )
        r.raise_for_status()
        data = r.json()
        token = data.get("token") or (data.get("payload") or {}).get("token")
        if not token:
            raise RuntimeError(f"Groww token response did not contain token: {str(data)[:220]}")
        return str(token)

    def _generate_token_totp(self, api_key: str, totp_secret: str) -> str:
        try:
            import pyotp
        except Exception as exc:
            raise RuntimeError("pyotp is required for TOTP authentication") from exc
        code = pyotp.TOTP(totp_secret).now()
        r = self._session.post(
            f"{GROWW_BASE_URL}/v1/token/api/access",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"key_type": "totp", "totp": code},
            timeout=12,
        )
        r.raise_for_status()
        data = r.json()
        token = data.get("token") or (data.get("payload") or {}).get("token")
        if not token:
            raise RuntimeError(f"Groww TOTP response did not contain token: {str(data)[:220]}")
        return str(token)

    def access_token(self, force_refresh: bool = False) -> str:
        with _LOCK:
            if self._access_token and not force_refresh and time.time() - self._token_loaded_at < 300:
                return self._access_token
            raw, flat = self._read_credentials()
            token = self._token_from_file(flat)
            if token and not force_refresh:
                self._access_token = token
                self._token_loaded_at = time.time()
                return token

            auth_mode = str(raw.get("auth_mode") or "").strip().lower() if isinstance(raw, dict) else ""
            api_key = _first(flat, ["api_key", "user_api_key", "groww_api_key"])
            api_secret = _first(flat, ["api_secret", "secret", "groww_api_secret"])
            totp_token = _first(flat, ["totp_token", "groww_totp_token"])
            totp_secret = _first(flat, ["totp_secret", "totpseed", "totp_key"])

            # v6.0.2: auth credentials are migrated as a validated coherent bundle.
            # API-key+secret approval is preferred over TOTP when both happen to be
            # present; Groww's TOTP flow uses a distinct TOTP token, not the approval API key.
            if auth_mode == "approval":
                if not (api_key and api_secret):
                    raise RuntimeError("Validated Groww approval credentials are incomplete.")
                token = self._generate_token_api_secret(api_key, api_secret)
            elif auth_mode == "totp":
                if not (totp_token and totp_secret):
                    raise RuntimeError("Validated Groww TOTP credentials are incomplete.")
                token = self._generate_token_totp(totp_token, totp_secret)
            elif api_key and api_secret:
                token = self._generate_token_api_secret(api_key, api_secret)
            elif totp_token and totp_secret:
                token = self._generate_token_totp(totp_token, totp_secret)
            else:
                raise RuntimeError("Groww access token expired and no validated refresh credential pair is available.")

            # Store only the fresh token in the same chmod-600 secret file; never log it.
            raw["access_token"] = token
            raw["access_token_refreshed_at"] = now_iso()
            self._write_credentials(raw)
            self._access_token = token
            self._token_loaded_at = time.time()
            return token

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token()}",
            "Accept": "application/json",
            "X-API-VERSION": "1.0",
        }

    def _request(self, method: str, path: str, *, params=None, json_body=None, timeout=15, retry_auth=True) -> Any:
        url = f"{GROWW_BASE_URL}{path}"
        headers = self._headers()
        if json_body is not None:
            headers["Content-Type"] = "application/json"
        try:
            r = self._session.request(method, url, headers=headers, params=params, json=json_body, timeout=timeout)
            if r.status_code in (401, 403) and retry_auth:
                self.access_token(force_refresh=True)
                return self._request(method, path, params=params, json_body=json_body, timeout=timeout, retry_auth=False)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict) and str(data.get("status") or "SUCCESS").upper() == "FAILURE":
                raise RuntimeError(str(data.get("error") or data.get("message") or data)[:300])
            return data.get("payload", data) if isinstance(data, dict) else data
        except Exception as exc:
            status=0
            try:status=int(getattr(getattr(exc,"response",None),"status_code",0) or 0)
            except Exception:pass
            # Historical candles are governed by data.py/history_control.py. Avoid flooding
            # system health with duplicate 429/invalid-history events that are already paced,
            # backed off and quarantined there. Other broker failures remain normal errors.
            if path == "/v1/historical/candles" and status in (400,404,422,429):
                raise
            if path == "/v1/live-data/ltp" and status in (400,404,422,429):
                raise
            if status==429:
                health("groww_rate_limit", "WARN", str(exc)[:300], {"path": path})
            else:
                health("groww", "ERROR", str(exc)[:300], {"path": path})
            raise

    def profile(self) -> Dict[str, Any]:
        return dict(self._request("GET", "/v1/user/detail") or {})

    def ltp(self, exchange_symbols: List[str]) -> Dict[str, float]:
        """Fetch LTPs without letting one bad batch kill the full NSE snapshot."""
        if not exchange_symbols:
            self._last_ltp_status={"at":now_iso(),"requested":0,"received":0,"batches":0,"failed_batches":0,"fallback_batches":0}
            return {}
        out: Dict[str, float] = {}
        failed_batches=0; fallback_batches=0; primary_batches=0
        failed_symbols: List[str] = []

        def absorb(payload: Any) -> None:
            if isinstance(payload, dict):
                for k, v in payload.items():
                    try:
                        out[str(k)] = float(v)
                    except Exception:
                        pass

        for i in range(0, len(exchange_symbols), 50):
            batch = exchange_symbols[i:i + 50]; primary_batches += 1
            try:
                payload = self._request(
                    "GET", "/v1/live-data/ltp",
                    params={"segment": "CASH", "exchange_symbols": ",".join(batch)},
                    timeout=10,
                ) or {}
                absorb(payload)
                continue
            except Exception as exc:
                failed_batches += 1
                status=0
                try: status=int(getattr(getattr(exc,"response",None),"status_code",0) or 0)
                except Exception: pass
                if status in (400,404,422) and len(batch)>10:
                    for j in range(0,len(batch),10):
                        sub=batch[j:j+10]; fallback_batches += 1
                        try:
                            payload = self._request(
                                "GET", "/v1/live-data/ltp",
                                params={"segment":"CASH","exchange_symbols":",".join(sub)},
                                timeout=10,
                            ) or {}
                            absorb(payload)
                        except Exception:
                            failed_symbols.extend(sub)
                else:
                    failed_symbols.extend(batch)

        self._last_ltp_status={
            "at":now_iso(),"requested":len(exchange_symbols),"received":len(out),
            "batches":primary_batches,"failed_batches":failed_batches,
            "fallback_batches":fallback_batches,"failed_symbols_sample":failed_symbols[:20],
            "policy":"PARTIAL_SUCCESS_50_BATCHES_BOUNDED_10_FALLBACK",
        }
        if failed_batches:
            health("live_ltp","WARN",f"LTP partial success {len(out)}/{len(exchange_symbols)}; failed batches={failed_batches}",
                   {"failed_batches":failed_batches,"fallback_batches":fallback_batches,"failed_symbols_sample":failed_symbols[:12]})
        return out

    def quote(self, trading_symbol: str, exchange: str = "NSE") -> Dict[str, Any]:
        return dict(self._request(
            "GET", "/v1/live-data/quote",
            params={"exchange": exchange, "segment": "CASH", "trading_symbol": trading_symbol},
            timeout=10,
        ) or {})

    def historical(self, groww_symbol: str, start_time: str, end_time: str, interval: str = "1day", exchange: str = "NSE") -> List[List[Any]]:
        payload = self._request(
            "GET", "/v1/historical/candles",
            params={
                "exchange": exchange,
                "segment": "CASH",
                "groww_symbol": groww_symbol,
                "start_time": start_time,
                "end_time": end_time,
                "candle_interval": interval,
            },
            timeout=20,
        ) or {}
        if isinstance(payload, dict):
            return list(payload.get("candles") or [])
        return []

    def holdings(self) -> Any:
        return self._request("GET", "/v1/holdings/user", timeout=12)

    def positions(self) -> Any:
        # Current Groww endpoint; if broker changes it, health shows degraded rather than guessing.
        return self._request("GET", "/v1/positions/user", params={"segment":"CASH"}, timeout=12)

    def place_cash_order(self, *, trading_symbol: str, side: str, quantity: int, product: str, limit_price: float, order_reference_id: str, exchange: str = "NSE") -> Dict[str, Any]:
        tx = "BUY" if side.upper() == "LONG" else "SELL"
        body = {
            "trading_symbol": trading_symbol,
            "quantity": int(quantity),
            "price": float(limit_price),
            "validity": "DAY",
            "exchange": exchange,
            "segment": "CASH",
            "product": product,
            "order_type": "LIMIT",
            "transaction_type": tx,
            "order_reference_id": order_reference_id,
        }
        return dict(self._request("POST", "/v1/order/create", json_body=body, timeout=15) or {})

    def order_status(self, groww_order_id: str, segment: str = "CASH") -> Dict[str, Any]:
        return dict(self._request("GET", f"/v1/order/status/{groww_order_id}", params={"segment":segment}, timeout=12) or {})

    def order_detail(self, groww_order_id: str, segment: str = "CASH") -> Dict[str, Any]:
        return dict(self._request("GET", f"/v1/order/detail/{groww_order_id}", params={"segment":segment}, timeout=12) or {})

    def order_trades(self, groww_order_id: str, segment: str = "CASH") -> List[Dict[str, Any]]:
        payload=self._request("GET", f"/v1/order/trades/{groww_order_id}", params={"segment":segment,"page":0,"page_size":50}, timeout=12) or {}
        if isinstance(payload,dict):
            rows=payload.get("trade_list") or payload.get("trades") or payload.get("order_trade_list") or []
            return [dict(x) for x in rows if isinstance(x,dict)]
        return []

    def order_list(self, segment: str = "CASH") -> List[Dict[str, Any]]:
        payload=self._request("GET", "/v1/order/list", params={"segment":segment,"page":0,"page_size":100}, timeout=12) or {}
        if isinstance(payload,dict):
            rows=payload.get("order_list") or payload.get("orders") or []
            return [dict(x) for x in rows if isinstance(x,dict)]
        return []

    def status_cached(self) -> Dict[str, Any]:
        if self._last_status:
            return dict(self._last_status)
        caps=self.credential_capabilities()
        return {"configured":self.configured(),"credential_capabilities":caps,"connected":False,"status":"UNKNOWN_NOT_PROBED","auth_mode":caps.get("auth_mode")}

    def static_ip_status_cached(self) -> Dict[str, Any]:
        expected=str(load_settings().get("expected_static_ip") or "").strip();valid=False
        if expected:
            try:ipaddress.ip_address(expected);valid=True
            except Exception:pass
        detected=self._last_ip
        return {"expected":expected,"detected":detected,"configured":bool(valid),"matches":bool(valid and detected and expected==detected),"cached":True}

    def status(self) -> Dict[str, Any]:
        if self._last_status and time.time()-self._last_status_at < 20:
            return dict(self._last_status)
        caps = self.credential_capabilities()
        data: Dict[str, Any] = {
            "configured": self.configured(),
            "credential_capabilities": caps,
            "connected": False,
            "status": "NOT_CONFIGURED" if not self.configured() else "CHECKING",
        }
        if not self.configured():
            return data
        try:
            prof = self.profile()
            data.update({
                "connected": True,
                "status": "CONNECTED",
                "nse_enabled": bool(prof.get("nse_enabled")),
                "bse_enabled": bool(prof.get("bse_enabled")),
                "active_segments": prof.get("active_segments") or [],
                "ddpi_enabled": prof.get("ddpi_enabled"),
                "auth_mode": caps.get("auth_mode") or "access_token",
                "checked_at": now_iso(),
            })
        except Exception as exc:
            data.update({"status": "AUTH_REQUIRED", "detail": str(exc)[:220], "checked_at": now_iso()})
        self._last_status = data
        self._last_status_at = time.time()
        return data

    def detected_public_ip(self) -> Optional[str]:
        if self._last_ip_at and time.time()-self._last_ip_at < 60:
            return self._last_ip
        try:
            r = self._session.get(PUBLIC_IP_URL, timeout=1.5)
            r.raise_for_status()
            ip = str(r.json().get("ip") or "").strip()
            ipaddress.ip_address(ip)
            self._last_ip=ip; self._last_ip_at=time.time()
            return ip
        except Exception:
            self._last_ip_at=time.time()
            return self._last_ip

    def static_ip_status(self) -> Dict[str, Any]:
        expected = str(load_settings().get("expected_static_ip") or "").strip()
        detected = self.detected_public_ip()
        valid_expected = False
        if expected:
            try:
                ipaddress.ip_address(expected)
                valid_expected = True
            except Exception:
                pass
        return {
            "expected": expected,
            "detected": detected,
            "configured": bool(valid_expected),
            "matches": bool(valid_expected and detected and expected == detected),
        }


def _round_to_tick(price: float, tick: float, up: bool) -> float:
    if tick <= 0:
        tick = 0.05
    steps = price / tick
    rounded = math.ceil(steps - 1e-12) if up else math.floor(steps + 1e-12)
    return round(max(tick, rounded * tick), 4)


def order_plan(side: str, ltp: float, tick_size: float = 0.05, stop_price: Optional[float] = None) -> Dict[str, Any]:
    side = side.upper()
    if ltp <= 0:
        raise ValueError("Live price unavailable")
    # Marketable limit with two independent caps: maximum ₹20k notional and maximum
    # ₹500 modeled loss to the recommendation's predefined invalidation.
    if side == "LONG":
        limit_price = _round_to_tick(ltp * 1.0015, tick_size, True)
        product = "CNC"
    elif side == "SHORT":
        limit_price = _round_to_tick(ltp * 0.9985, tick_size, False)
        product = "MIS"
    else:
        raise ValueError("side must be LONG or SHORT")
    notional_qty = int(TRADE_NOTIONAL_RUPEES // max(limit_price, ltp if side == "SHORT" else limit_price))
    risk_qty = notional_qty
    risk_per_share = 0.0
    if stop_price is not None:
        try:
            sp=float(stop_price)
            risk_per_share=abs(limit_price-sp)
            if risk_per_share>0:
                risk_qty=int(MAX_RUPEE_RISK_PER_TRADE // risk_per_share)
        except Exception:
            pass
    quantity=max(0,min(notional_qty,risk_qty))
    return {
        "side": side,
        "product": product,
        "ltp": round(float(ltp), 4),
        "limit_price": limit_price,
        "quantity": quantity,
        "notional_cap": TRADE_NOTIONAL_RUPEES,
        "risk_cap_rupees": MAX_RUPEE_RISK_PER_TRADE,
        "risk_per_share": round(risk_per_share,4),
        "estimated_risk_to_stop": round(quantity*risk_per_share,2),
        "estimated_notional": round(quantity * limit_price, 2),
        "sizing_rule": "MIN_20K_NOTIONAL_CAP_500_RUPEE_STOP_RISK_CAP",
        "note": "₹20,000 is the maximum notional; risk-to-stop may reduce quantity. LONG uses CNC delivery; SHORT uses MIS intraday. Limit execution is not guaranteed.",
    }



broker = GrowwBroker()
