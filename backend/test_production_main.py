import production_main


def test_production_entrypoint_exposes_required_routes():
    paths = {route.path for route in production_main.app.routes}
    required = {
        "/health",
        "/api/production/status",
        "/api/groww/status",
        "/api/groww/reconnect",
        "/api/feed/status",
        "/api/daily-recommendations",
        "/api/daily-recommendations/refresh",
        "/api/memory/status",
        "/api/provider-health",
        "/api/agent-performance",
        "/api/llm-analyses",
        "/api/exit-signals",
        "/api/orders/sell-position",
    }
    assert required.issubset(paths)
    assert production_main.app.version == "2.0.0"
