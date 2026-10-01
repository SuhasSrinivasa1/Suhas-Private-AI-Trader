from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
LOGS = ROOT / "logs"
STATIC = ROOT / "static"
SECURE = DATA / "secure"
DB_PATH = DATA / "psscanner_quant.db"
SETTINGS_PATH = DATA / "settings.json"
CREDENTIALS_PATH = SECURE / "groww_credentials.json"
INSTRUMENTS_PATH = DATA / "instruments.csv"
UNIVERSE_PATH = DATA / "universe.json"
DISCOVERY_CACHE = DATA / "strategy_discovery.json"
HEARTBEAT_PATH = DATA / "heartbeat.json"

for p in (DATA, LOGS, SECURE):
    p.mkdir(parents=True, exist_ok=True)
