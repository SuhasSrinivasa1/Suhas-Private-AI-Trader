import production21_main


def test_production21_entrypoint_exposes_full_universe_and_objective_routes():
    paths = {route.path for route in production21_main.app.routes}
    assert "/api/production21/status" in paths
    assert "/api/universe/predictions" in paths
    assert "/api/capital-objective" in paths
    assert production21_main.app.version in {"2.1.0", "2.2.0"}


def test_capital_objective_is_explicitly_not_guaranteed():
    objective = production21_main.capital_objective()
    assert objective["starting_capital_inr"] == 20000
    assert objective["stretch_target_inr"] == 100000
    assert objective["guaranteed"] is False
    assert objective["zero_loss_guaranteed"] is False
