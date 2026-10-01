from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from .constants import IST, MARKET_OPEN, MARKET_CLOSE

# Official NSE equity trading holidays for calendar year 2026.
# Source: NSE India, Market Timings & Holidays, retrieved 2026-09-24.
# URL intentionally stored as metadata; the application does not depend on web access
# for 2026 session arithmetic.
NSE_HOLIDAY_SOURCE = "https://www.nseindia.com/resources/exchange-communication-holidays"
NSE_EQUITY_HOLIDAYS_2026 = {
    date(2026,1,15): "Municipal Corporation Election - Maharashtra",
    date(2026,1,26): "Republic Day",
    date(2026,3,3): "Holi",
    date(2026,3,26): "Shri Ram Navami",
    date(2026,3,31): "Shri Mahavir Jayanti",
    date(2026,4,3): "Good Friday",
    date(2026,4,14): "Dr. Baba Saheb Ambedkar Jayanti",
    date(2026,5,1): "Maharashtra Day",
    date(2026,5,28): "Bakri Id",
    date(2026,6,26): "Muharram",
    date(2026,9,14): "Ganesh Chaturthi",
    date(2026,10,2): "Mahatma Gandhi Jayanti",
    date(2026,10,20): "Dussehra",
    date(2026,11,10): "Diwali-Balipratipada",
    date(2026,11,24): "Prakash Gurpurb Sri Guru Nanak Dev",
    date(2026,12,25): "Christmas",
}


def holiday_map(year: int) -> Dict[date, str]:
    if year == 2026:
        return dict(NSE_EQUITY_HOLIDAYS_2026)
    return {}


def is_regular_trading_day(d: date) -> bool:
    if d.weekday() >= 5:
        return False
    return d not in holiday_map(d.year)




def first_trading_day_of_week(d: date) -> date:
    x = d - timedelta(days=d.weekday())
    for _ in range(7):
        if is_regular_trading_day(x):
            return x
        x += timedelta(days=1)
    return d


def first_trading_day_of_month(d: date) -> date:
    x = date(d.year, d.month, 1)
    for _ in range(10):
        if is_regular_trading_day(x):
            return x
        x += timedelta(days=1)
    return d

def previous_trading_day(d: date) -> date:
    x=d
    while not is_regular_trading_day(x):
        x-=timedelta(days=1)
    return x


def next_trading_day(d: date, include_today: bool=False) -> date:
    x=d if include_today else d+timedelta(days=1)
    for _ in range(370):
        if is_regular_trading_day(x): return x
        x+=timedelta(days=1)
    return x


def period_end_date(book: str, now: Optional[datetime]=None) -> date:
    now=now or datetime.now(IST)
    if book in ("WEEKLY","ETF"):
        friday=now.date()+timedelta(days=max(0,4-now.weekday()))
        return previous_trading_day(friday)
    if book=="MONTHLY":
        if now.month==12:
            first_next=date(now.year+1,1,1)
        else:
            first_next=date(now.year,now.month+1,1)
        return previous_trading_day(first_next-timedelta(days=1))
    return now.date()


def regular_sessions(start: date, end: date) -> List[date]:
    if end < start: return []
    out=[];d=start
    while d<=end:
        if is_regular_trading_day(d):out.append(d)
        d+=timedelta(days=1)
    return out


def remaining_sessions(book: str, now: Optional[datetime]=None) -> float:
    now=now or datetime.now(IST)
    end=period_end_date(book,now)
    if now.date()>end:return 0.0
    future=regular_sessions(now.date()+timedelta(days=1),end)
    frac=0.0
    if is_regular_trading_day(now.date()) and now.date()<=end:
        t=now.time().replace(tzinfo=None)
        if t<MARKET_OPEN:frac=1.0
        elif t<MARKET_CLOSE:
            a=MARKET_OPEN.hour*60+MARKET_OPEN.minute
            b=MARKET_CLOSE.hour*60+MARKET_CLOSE.minute
            c=t.hour*60+t.minute+t.second/60.0
            frac=max(0.0,min(1.0,(b-c)/max(1,b-a)))
    return round(len(future)+frac,3)


def add_trading_sessions(start: datetime, sessions: int) -> datetime:
    sessions=max(0,int(sessions));d=start.date();left=sessions
    while left>0:
        d+=timedelta(days=1)
        if is_regular_trading_day(d):left-=1
    return datetime.combine(d,start.timetz()).astimezone(IST) if start.tzinfo else datetime.combine(d,start.time()).replace(tzinfo=IST)


def status(now: Optional[datetime]=None) -> Dict[str, object]:
    now=now or datetime.now(IST)
    h=holiday_map(now.year)
    return {
        "year":now.year,
        "source":"NSE_OFFICIAL_STATIC_2026" if now.year==2026 else "WEEKDAY_FALLBACK",
        "source_url":NSE_HOLIDAY_SOURCE,
        "holiday_count":len(h),
        "today_is_regular_session":is_regular_trading_day(now.date()),
        "weekly_period_end":period_end_date("WEEKLY",now).isoformat(),
        "monthly_period_end":period_end_date("MONTHLY",now).isoformat(),
        "weekly_remaining_sessions":remaining_sessions("WEEKLY",now),
        "monthly_remaining_sessions":remaining_sessions("MONTHLY",now),
        "warning":None if now.year==2026 else "No packaged official holiday calendar for this year; weekday fallback is in use.",
    }
