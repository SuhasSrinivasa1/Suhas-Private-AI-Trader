from __future__ import annotations

from datetime import time
from zoneinfo import ZoneInfo

APP_NAME = "PS Scanner Quant"
VERSION = "6.8.1"
IST = ZoneInfo("Asia/Kolkata")
HOST = "127.0.0.1"
PORT = 8765

# User-requested invariant: every manual order intent is capped at ₹20,000 notional.
TRADE_NOTIONAL_RUPEES = 20_000.0
# Risk-first sizing: ₹20k is the maximum notional, not a requirement to use all of it.
MAX_RUPEE_RISK_PER_TRADE = 500.0

MARKET_OPEN = time(9, 15)
INTRADAY_ENTRY_CUTOFF = time(15, 0)
SHORT_HARD_EXIT = time(15, 0)
CIRCUIT_LIVE_CUTOFF = time(15, 0)
CIRCUIT_NEXTDAY_PREP_START = time(14, 40)
CIRCUIT_NEXTDAY_FREEZE = time(15, 0)
CIRCUIT_NEXTDAY_FREEZE_END = time(15, 20)
GLOBAL_INDIA_FREEZE_TIME = time(9, 0)
MARKET_CLOSE = time(15, 30)
POST_MARKET_START = time(15, 40)
STABILITY_FINALIZE_TIME = time(20, 50)
# Freeze Reliability v6.4.8: build the slate before the opening bell.
# The official freeze target is 09:00 IST; if the app was asleep/offline or a scan
# failed, deterministic recovery remains open through 15:25 without relaxing gates.
HORIZON_RESEARCH_START = time(6, 0)
HORIZON_FREEZE_START = time(9, 0)
HORIZON_FREEZE_END = time(9, 12)
HORIZON_RECOVERY_END = time(15, 25)
# Compatibility aliases: publication is now a morning workflow.
HORIZON_PUBLISH_START = HORIZON_FREEZE_START
HORIZON_PUBLISH_END = HORIZON_FREEZE_END

GROWW_BASE_URL = "https://api.groww.in"
GROWW_INSTRUMENT_CSV = "https://growwapi-assets.groww.in/instruments/instrument.csv"
NIFTY500_CSV = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"
PUBLIC_IP_URL = "https://api.ipify.org?format=json"

BOOKS = ("INTRADAY", "WEEKLY", "MONTHLY", "ETF", "CIRCUIT", "CIRCUIT_NEXTDAY", "INTERNATIONAL", "GLOBAL_INDIA_LONG", "GLOBAL_INDIA_SHORT")
