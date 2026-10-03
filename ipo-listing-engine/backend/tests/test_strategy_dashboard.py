from app.strategy_dashboard import (
    FamilyEvidence,
    STRATEGY_FAMILIES,
    promotion_status,
    ranking_score,
)


def test_catalog_has_expected_breadth():
    assert len(STRATEGY_FAMILIES) >= 15


def test_untested_family_is_research():
    assert promotion_status(FamilyEvidence("x")) == "RESEARCH"


def test_positive_mature_evidence_can_be_champion():
    evidence = FamilyEvidence(
        family_id="x",
        trades=42,
        wins=25,
        net_pnl_bps=840,
        gross_profit_bps=2100,
        gross_loss_bps=-1200,
        max_drawdown_bps=480,
        last_20_net_bps=220,
        out_of_sample_trades=12,
        out_of_sample_net_pnl_bps=260,
        walk_forward_windows=3,
    )
    assert promotion_status(evidence) == "CHAMPION"
    assert ranking_score(evidence) > 0


def test_recent_negative_evidence_is_penalized():
    good = FamilyEvidence(
        family_id="x",
        trades=40,
        wins=24,
        net_pnl_bps=600,
        gross_profit_bps=1800,
        gross_loss_bps=-1100,
        max_drawdown_bps=400,
        last_20_net_bps=100,
    )
    weakening = FamilyEvidence(
        family_id="x",
        trades=40,
        wins=24,
        net_pnl_bps=600,
        gross_profit_bps=1800,
        gross_loss_bps=-1100,
        max_drawdown_bps=400,
        last_20_net_bps=-100,
    )
    assert ranking_score(good) > ranking_score(weakening)


def test_mature_in_sample_only_evidence_cannot_be_champion():
    evidence = FamilyEvidence(
        family_id="x",
        trades=50,
        wins=32,
        net_pnl_bps=1200,
        gross_profit_bps=2600,
        gross_loss_bps=-1100,
        max_drawdown_bps=300,
        last_20_net_bps=350,
    )
    assert promotion_status(evidence) == "CHALLENGER"
