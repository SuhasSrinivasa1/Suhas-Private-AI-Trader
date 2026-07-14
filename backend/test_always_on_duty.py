import asyncio

from always_on_duty import AlwaysOnDutyEngine


class FakeStore:
    def __init__(self):
        self.health = []

    def update_provider_health(self, provider, **kwargs):
        self.health.append((provider, kwargs))


class FakeRuntime:
    def __init__(self):
        self.store = FakeStore()
        self.llm_payloads = []

    async def trigger_llm_analysis(self, **kwargs):
        self.llm_payloads.append(kwargs)
        return {"ok": True}


class FakeCore:
    GROWW_LIVE_EXECUTION_ENABLED = False
    SCANNER_UNIVERSE = ["AAA", "BBB"]
    latest_market_regime = {"score": 50, "label": "neutral"}
    latest_prices = {}
    latest_opportunities = {}
    recommendation_cache = {}
    last_scan_at = None
    last_scan_error = None

    def _market_open_now(self):
        return False

    def _broker_configured(self):
        return True

    async def _market_regime_score(self):
        return {"score": 61, "label": "neutral"}

    async def _coarse_scan(self):
        return [
            {"symbol": "AAA", "exchange": "NSE", "coarse_score": 80},
            {"symbol": "BBB", "exchange": "NSE", "coarse_score": 70},
        ]

    def _signal_identity(self, item):
        return f"{item.get('symbol')}:{item.get('state')}"

    def _mask_error(self, exc):
        return f"{exc.__class__.__name__}: {exc}"

    async def broadcast(self, message):
        return None


async def fake_scan(candidate):
    return {
        "symbol": candidate["symbol"],
        "exchange": "NSE",
        "state": "BUY",
        "action": "BUY",
        "confidence": candidate["coarse_score"],
        "rank_score": candidate["coarse_score"],
        "entry_price": 100,
        "target_price": 104,
        "stop_loss": 98,
        "reasons": [],
    }


def test_off_hours_buy_is_downgraded_to_watch():
    item = AlwaysOnDutyEngine._as_watch_candidate(
        {"symbol": "AAA", "state": "BUY", "action": "BUY", "reasons": []},
        "2026-07-14T00:00:00+00:00",
    )
    assert item["state"] == "WATCHING"
    assert item["execution_eligible"] is False
    assert item["paper_call_logged"] is False
    assert item["requires_live_revalidation"] is True


def test_run_once_uses_real_research_path_without_actionable_buy():
    core = FakeCore()
    runtime = FakeRuntime()
    engine = AlwaysOnDutyEngine(core, runtime, fake_scan)
    result = asyncio.run(engine.run_once(force=True, reason="test"))

    assert result["status"] == "ready"
    assert result["mode"] == "off_hours_research"
    assert result["items"]
    assert all(item["state"] != "BUY" for item in result["items"])
    assert all(item["execution_eligible"] is False for item in result["items"])
    assert core.latest_opportunities
    assert runtime.store.health[-1][0] == "off_hours_research"


def test_status_never_marks_off_hours_execution_eligible():
    engine = AlwaysOnDutyEngine(FakeCore(), FakeRuntime(), fake_scan)
    status = engine.status()
    assert status["market_open"] is False
    assert status["buy_sell_execution_eligible"] is False
