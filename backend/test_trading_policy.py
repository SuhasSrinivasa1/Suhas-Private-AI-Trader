from datetime import datetime, timezone

from trading_policy import TradingPolicy, evaluate_entry


def base_request():
    return {
        'symbol': 'AAPL',
        'market': 'NASDAQ',
        'direction': 'long',
        'current_price': 101.0,
        'reference_price': 100.0,
        'entry_price': 101.0,
        'stop_loss': 99.0,
        'target_price': 105.0,
        'quantity': 10,
        'portfolio_value': 100000.0,
        'price_timestamp': datetime.now(timezone.utc),
        'quote_source': 'verified-live-feed',
        'confirmation_source_count': 2,
        'news_checked': True,
        'technical_checked': True,
        'portfolio_checked': True,
    }


def test_valid_long_is_buy_in_paper_mode():
    result = evaluate_entry(**base_request())
    assert result['eligible'] is True
    assert result['action'] == 'BUY'
    assert result['execution_mode'] == 'paper'


def test_live_execution_is_blocked_by_default():
    request = base_request()
    request['live_execution_requested'] = True
    result = evaluate_entry(**request)
    assert result['eligible'] is False
    assert result['execution_mode'] == 'paper'


def test_chasing_is_rejected():
    request = base_request()
    request['current_price'] = 103.0
    result = evaluate_entry(**request)
    assert result['action'] == 'WAIT'
    assert any('Do not chase' in reason for reason in result['reasons'])


def test_controlled_policy_override_can_enable_live_mode():
    request = base_request()
    request['live_execution_requested'] = True
    result = evaluate_entry(**request, policy=TradingPolicy(allow_live_execution=True))
    assert result['eligible'] is True
    assert result['execution_mode'] == 'live'
