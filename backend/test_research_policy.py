import json
from pathlib import Path


def test_research_contract_is_groww_only():
    rules=json.loads((Path(__file__).parents[1]/'config'/'research_rules.json').read_text())
    assert rules['schema_version']=='2.4.0'
    assert rules['data_provider']=='Groww Trading API'
    assert rules['mock_market_data_allowed'] is False
    assert rules['walk_forward_required'] is True
    assert rules['monte_carlo_required'] is True
    assert rules['strategy_approval']['paper_observation_required'] is True
    assert rules['strategy_approval']['automatic_execution'] is False
    assert rules['calls_and_results']['real_groww_prices_only'] is True
    assert rules['calls_and_results']['mock_calls_forbidden'] is True
