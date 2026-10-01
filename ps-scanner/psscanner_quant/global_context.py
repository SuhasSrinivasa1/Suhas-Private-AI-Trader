from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict

from .constants import IST
from .db import get_state, health, now_iso, set_state

# Major liquid global reference markets, cross-asset drivers, sector ETFs and selected
# large foreign companies. This is a practical overnight information set, not a claim to
# cover every exchange/security in the world.
PROXIES = {
    # Broad US / Europe / Asia-Pacific
    "SP500":"^GSPC", "NASDAQ":"^IXIC", "DOW":"^DJI", "RUSSELL2000":"^RUT",
    "STOXX50":"^STOXX50E", "FTSE100":"^FTSE", "DAX":"^GDAXI", "CAC40":"^FCHI",
    "NIKKEI225":"^N225", "HANGSENG":"^HSI", "SHANGHAI":"000001.SS", "KOSPI":"^KS11",
    "SINGAPORE_STI":"^STI", "TAIWAN":"^TWII", "ASX200":"^AXJO",
    # India / volatility / FX / commodities
    "INDIA_VIX":"^INDIAVIX", "USDINR":"INR=X", "DXY":"DX-Y.NYB",
    "CRUDE":"CL=F", "GOLD":"GC=F", "COPPER":"HG=F", "NATGAS":"NG=F",
    # US sector/industry ETFs
    "US_TECH":"XLK", "US_SEMIS":"SOXX", "US_FINANCIALS":"XLF", "US_BANKS":"KBE",
    "US_ENERGY":"XLE", "US_HEALTH":"XLV", "US_INDUSTRIALS":"XLI", "US_DISCRETIONARY":"XLY",
    "US_STAPLES":"XLP", "US_MATERIALS":"XLB",
    # Foreign-company cluster signals used in India industry mappings
    "AAPL":"AAPL", "MSFT":"MSFT", "NVDA":"NVDA", "ORCL":"ORCL",
    "JPM":"JPM", "GS":"GS", "BAC":"BAC",
    "XOM":"XOM", "SHEL":"SHEL",
    "LLY":"LLY", "NVO":"NVO",
    "TSLA":"TSLA", "TM":"TM",
    "BHP":"BHP", "RIO":"RIO",
}


def _age_ok(state: Dict[str, Any], minutes: int) -> bool:
    try:
        ts=datetime.fromisoformat(str(state.get('generated_at')))
        if ts.tzinfo is None: ts=ts.replace(tzinfo=IST)
        return datetime.now(IST)-ts <= timedelta(minutes=minutes)
    except Exception:return False


def _move_from_series(close) -> float | None:
    try:
        close=close.dropna()
        if len(close)<2:return None
        idx=close.index
        try:
            last_day=idx[-1].date()
            mask=[x.date()==last_day for x in idx]
            same=close[mask]
            if len(same)>=2 and float(same.iloc[0])!=0:
                return (float(same.iloc[-1])/float(same.iloc[0])-1)*100
        except Exception:pass
        vals=[float(x) for x in close.tolist()]
        if len(vals)>=2 and vals[-2]!=0:return (vals[-1]/vals[-2]-1)*100
    except Exception:pass
    return None


def _extract_close(frame, ticker:str):
    if frame is None or len(frame)==0:return None
    try:
        cols=frame.columns
        # group_by='ticker' yields (ticker, OHLCV) for multi-ticker downloads.
        if getattr(cols,'nlevels',1)>1:
            try:return frame[ticker]['Close']
            except Exception:
                try:return frame['Close'][ticker]
                except Exception:return None
        if 'Close' in cols:return frame['Close']
    except Exception:return None
    return None


def snapshot(force: bool=False) -> Dict[str, Any]:
    old=get_state('global_context',{}) or {}
    if old and not force and _age_ok(old,5):return old
    moves={}; errors=[]; tickers={}; ticker_to_label={v:k for k,v in PROXIES.items()}
    try:
        import yfinance as yf
        ticker_list=list(PROXIES.values())
        # Batch requests avoid dozens of serial HTTP calls and keep this background worker
        # from starving scanners. Hourly bars provide current-session/overnight movement.
        hourly=yf.download(ticker_list,period='5d',interval='60m',auto_adjust=False,progress=False,threads=True,group_by='ticker')
        missing=[]
        for ticker in ticker_list:
            label=ticker_to_label[ticker]
            mv=_move_from_series(_extract_close(hourly,ticker))
            if mv is None:missing.append(ticker)
            else:moves[label]=round(float(mv),4);tickers[label]=ticker
        if missing:
            daily=yf.download(missing,period='5d',interval='1d',auto_adjust=False,progress=False,threads=True,group_by='ticker')
            for ticker in missing:
                label=ticker_to_label[ticker]
                mv=_move_from_series(_extract_close(daily,ticker))
                if mv is not None:moves[label]=round(float(mv),4);tickers[label]=ticker
    except Exception as exc:
        errors.append(str(exc)[:240])
    broad=[moves.get(k) for k in ('SP500','NASDAQ','DOW','RUSSELL2000','STOXX50','FTSE100','DAX','NIKKEI225','HANGSENG','ASX200') if k in moves]
    equity=sum(broad)/len(broad) if broad else 0.0
    vix=moves.get('INDIA_VIX',0.0);fx=moves.get('USDINR',0.0);dxy=moves.get('DXY',0.0)
    risk_score=equity-max(0.0,vix)*0.18-abs(fx)*0.08-abs(dxy)*0.04
    if risk_score>0.6:state='RISK_ON'
    elif risk_score<-0.6:state='RISK_OFF'
    else:state='MIXED'
    out={'generated_at':now_iso(),'moves_pct':moves,'tickers':tickers,'risk_state':state,'risk_score':round(risk_score,3),'equity_cue_pct':round(equity,3),'errors':errors,'stale':not bool(moves),'coverage':len(moves),'coverage_target':len(PROXIES),'policy':'MAJOR_LIQUID_GLOBAL_MARKETS_SECTOR_ETFS_COMPANY_CLUSTERS_AND_CROSS_ASSET_DRIVERS'}
    if moves:set_state('global_context',out)
    elif old:
        old=dict(old);old['stale']=True;old['refresh_errors']=errors;return old
    else:health('global_context','WARN','No live global proxy data',{'errors':errors})
    return out
