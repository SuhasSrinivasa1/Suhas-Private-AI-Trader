from datetime import datetime, timedelta, timezone
from research_engine import ResearchEngine, STRATEGIES


def rows(n=700):
    out=[]; p=100.0; start=datetime(2023,1,1,tzinfo=timezone.utc)
    for i in range(n):
        p *= 1 + (0.002 if i%7 else -0.004)
        out.append({"timestamp":start+timedelta(days=i),"open":p*.998,"high":p*1.015,"low":p*.985,"close":p,"volume":100000+i*100})
    return out


def engine():
    return ResearchEngine(type('C',(),{})(),None,type('Calls',(),{'summary':lambda self:{'resolved_calls':60,'accuracy_pct':65,'learning':{'wilson_lower_bound':.52}}})())


def test_catalog_has_three_strategies():
    assert len(STRATEGIES) >= 3


def test_regime_uses_rows():
    assert engine().regime(rows())['available'] is True


def test_backtest_is_deterministic_and_cost_aware():
    result=engine().backtest_rows('trend_macd_volume',rows())
    assert result['data_source']=='Groww Trading API'
    assert result['costs_bps_round_trip']==20
    assert 'max_drawdown_pct' in result['metrics']


def test_edge_monitor_requires_resolved_sample():
    assert engine().calls_edge()['state'] in {'ACTIVE','DETERIORATING'}
