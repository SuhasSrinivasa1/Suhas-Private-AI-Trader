from app.replay_tournament import ReplayPoint, ReplayTournament
from app.strategy_registry import StrategyDefinition, StrategyOutput


def _long(features):
    assert set(features) == {"signal"}
    return StrategyOutput(
        strategy_id="s1",
        direction="LONG" if features["signal"] > 0 else "WAIT",
        score=0.8,
        expected_return_bps=120,
        expected_risk_bps=60,
        reason_codes=("TEST_SIGNAL",),
    )


def test_replay_persists_costs_mfe_mae_and_oos_split():
    strategy = StrategyDefinition(
        strategy_id="s1",
        family="opening_drive",
        version="1",
        source="test",
        required_features=("signal",),
        evaluator=_long,
    )
    tape = [
        ReplayPoint(
            timestamp="2026-10-05T10:00:00+05:30",
            next_timestamp="2026-10-05T10:01:00+05:30",
            features={"signal": 1.0},
            current_price=100.0,
            next_price=105.0,
            interval_high=106.0,
            interval_low=99.0,
            spread_bps=10.0,
            slippage_bps=5.0,
            impact_bps=5.0,
            charges_bps=5.0,
        ),
        ReplayPoint(
            timestamp="2026-10-05T10:01:00+05:30",
            next_timestamp="2026-10-05T10:02:00+05:30",
            features={"signal": 1.0},
            current_price=105.0,
            next_price=104.0,
        ),
        ReplayPoint(
            timestamp="2026-10-05T10:02:00+05:30",
            next_timestamp="2026-10-05T10:03:00+05:30",
            features={"signal": 1.0},
            current_price=104.0,
            next_price=110.0,
        ),
        ReplayPoint(
            timestamp="2026-10-05T10:03:00+05:30",
            next_timestamp="2026-10-05T10:04:00+05:30",
            features={"signal": 1.0},
            current_price=110.0,
            next_price=111.0,
        ),
    ]

    result = ReplayTournament(training_fraction=0.5).run([strategy], tape)[0]

    assert result.trades == 4
    assert result.out_of_sample_trades == 2
    assert result.trades_detail[0].mfe_bps > 0
    assert result.trades_detail[0].mae_bps < 0
    assert result.trades_detail[0].spread_bps == 10.0
    assert result.trades_detail[0].time_to_mfe_seconds == 60.0
    assert result.trades_detail[2].sample == "OUT_OF_SAMPLE"
    assert result.max_drawdown_bps >= 0


def test_wait_signal_creates_no_hindsight_trade():
    def wait(features):
        return StrategyOutput(
            strategy_id="wait",
            direction="WAIT",
            score=0.0,
            expected_return_bps=0.0,
            expected_risk_bps=0.0,
            reason_codes=("NO_SIGNAL",),
        )

    strategy = StrategyDefinition(
        strategy_id="wait",
        family="vwap_hold_reclaim",
        version="1",
        source="test",
        required_features=("signal",),
        evaluator=wait,
    )
    tape = [
        ReplayPoint(
            timestamp="2026-10-05T10:00:00+05:30",
            features={"signal": 0.0},
            current_price=100.0,
            next_price=150.0,
        )
    ]
    result = ReplayTournament().run([strategy], tape)[0]
    assert result.trades == 0
    assert result.net_pnl_bps == 0.0
