import production_main


def test_production_entrypoint_exposes_required_routes():
    paths = {route.path for route in production_main.app.routes}
    required = {
        "/health",
        "/api/production/status",
        "/api/groww/status",
        "/api/groww/reconnect",
        "/api/daily-recommendations",
        "/api/daily-recommendations/refresh",
    }
    assert required.issubset(paths)
    assert production_main.app.version == "1.0.0"
