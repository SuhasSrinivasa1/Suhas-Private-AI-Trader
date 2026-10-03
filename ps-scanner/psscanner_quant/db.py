from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from .constants import IST
from .paths import DB_PATH


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS recommendations (
  recommendation_id TEXT PRIMARY KEY,
  book TEXT NOT NULL,
  period_key TEXT NOT NULL,
  symbol TEXT NOT NULL,
  exchange TEXT NOT NULL DEFAULT 'NSE',
  side TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'LIVE',
  score REAL NOT NULL,
  confidence REAL NOT NULL DEFAULT 0,
  entry_price REAL NOT NULL,
  current_price REAL NOT NULL,
  target_price REAL,
  stop_price REAL,
  target_pct REAL,
  horizon TEXT NOT NULL,
  regime TEXT NOT NULL,
  strategy_ids_json TEXT NOT NULL DEFAULT '[]',
  rationale_json TEXT NOT NULL DEFAULT '{}',
  feature_snapshot_json TEXT NOT NULL DEFAULT '{}',
  data_confidence REAL NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  closed_at TEXT,
  result TEXT,
  close_reason TEXT,
  max_favourable_pct REAL NOT NULL DEFAULT 0,
  max_adverse_pct REAL NOT NULL DEFAULT 0,
  software_version TEXT,
  config_hash TEXT,
  decision_id TEXT,
  audit_envelope_json TEXT NOT NULL DEFAULT '{}',
  UNIQUE(book, period_key, symbol, side, created_at)
);
CREATE INDEX IF NOT EXISTS idx_recs_book_state ON recommendations(book,state,score DESC);
CREATE INDEX IF NOT EXISTS idx_recs_period ON recommendations(book,period_key,state);

-- Defense-in-depth frozen-identity interlock. Early close does not release a frozen
-- Weekly/Monthly symbol while the two calendar periods overlap.
DROP TRIGGER IF EXISTS trg_weekly_monthly_symbol_exclusive_insert;
DROP TRIGGER IF EXISTS trg_weekly_monthly_symbol_exclusive_update;
CREATE TRIGGER trg_weekly_monthly_symbol_exclusive_insert
BEFORE INSERT ON recommendations
WHEN NEW.book IN ('WEEKLY','MONTHLY') AND COALESCE(NEW.result,'')<>'VOID'
BEGIN
  SELECT CASE WHEN EXISTS (
    SELECT 1 FROM recommendations r
    WHERE r.book IN ('WEEKLY','MONTHLY') AND r.book<>NEW.book
      AND UPPER(r.symbol)=UPPER(NEW.symbol) AND COALESCE(r.result,'')<>'VOID'
      AND (CASE WHEN NEW.book='WEEKLY' THEN date(NEW.period_key) ELSE date(NEW.period_key||'-01') END)
          <= (CASE WHEN r.book='WEEKLY' THEN date(r.period_key,'+6 day') ELSE date(r.period_key||'-01','+1 month','-1 day') END)
      AND (CASE WHEN r.book='WEEKLY' THEN date(r.period_key) ELSE date(r.period_key||'-01') END)
          <= (CASE WHEN NEW.book='WEEKLY' THEN date(NEW.period_key,'+6 day') ELSE date(NEW.period_key||'-01','+1 month','-1 day') END)
  ) THEN RAISE(ABORT,'WEEKLY_MONTHLY_PERIOD_IDENTITY_COLLISION') END;
END;

CREATE TRIGGER trg_weekly_monthly_symbol_exclusive_update
BEFORE UPDATE OF book,period_key,symbol ON recommendations
WHEN NEW.book IN ('WEEKLY','MONTHLY') AND COALESCE(NEW.result,'')<>'VOID'
BEGIN
  SELECT CASE WHEN EXISTS (
    SELECT 1 FROM recommendations r
    WHERE r.recommendation_id<>NEW.recommendation_id
      AND r.book IN ('WEEKLY','MONTHLY') AND r.book<>NEW.book
      AND UPPER(r.symbol)=UPPER(NEW.symbol) AND COALESCE(r.result,'')<>'VOID'
      AND (CASE WHEN NEW.book='WEEKLY' THEN date(NEW.period_key) ELSE date(NEW.period_key||'-01') END)
          <= (CASE WHEN r.book='WEEKLY' THEN date(r.period_key,'+6 day') ELSE date(r.period_key||'-01','+1 month','-1 day') END)
      AND (CASE WHEN r.book='WEEKLY' THEN date(r.period_key) ELSE date(r.period_key||'-01') END)
          <= (CASE WHEN NEW.book='WEEKLY' THEN date(NEW.period_key,'+6 day') ELSE date(NEW.period_key||'-01','+1 month','-1 day') END)
  ) THEN RAISE(ABORT,'WEEKLY_MONTHLY_PERIOD_IDENTITY_COLLISION') END;
END;

CREATE TABLE IF NOT EXISTS strategies (
  strategy_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  family TEXT NOT NULL,
  horizon TEXT NOT NULL,
  side TEXT NOT NULL,
  params_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'CHALLENGER',
  source TEXT NOT NULL DEFAULT 'BUILTIN',
  version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_strategies_status ON strategies(horizon,status,family);

CREATE TABLE IF NOT EXISTS strategy_stats (
  strategy_id TEXT NOT NULL,
  regime TEXT NOT NULL,
  sample_count INTEGER NOT NULL DEFAULT 0,
  win_rate REAL,
  avg_r REAL,
  profit_factor REAL,
  sharpe REAL,
  sortino REAL,
  max_drawdown REAL,
  robustness REAL,
  walk_forward_score REAL,
  score REAL,
  last_validated_at TEXT,
  PRIMARY KEY(strategy_id,regime),
  FOREIGN KEY(strategy_id) REFERENCES strategies(strategy_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS strategy_discovery (
  fingerprint TEXT PRIMARY KEY,
  discovered_at TEXT NOT NULL,
  source_name TEXT NOT NULL,
  title TEXT NOT NULL,
  source_url TEXT,
  published_at TEXT,
  abstract TEXT,
  mapped_family TEXT,
  status TEXT NOT NULL DEFAULT 'DISCOVERED',
  metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS order_previews (
  preview_token TEXT PRIMARY KEY,
  recommendation_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  consumed INTEGER NOT NULL DEFAULT 0,
  payload_json TEXT NOT NULL,
  FOREIGN KEY(recommendation_id) REFERENCES recommendations(recommendation_id)
);

CREATE TABLE IF NOT EXISTS orders (
  local_order_id TEXT PRIMARY KEY,
  recommendation_id TEXT NOT NULL,
  order_reference_id TEXT NOT NULL UNIQUE,
  groww_order_id TEXT,
  symbol TEXT NOT NULL,
  side TEXT NOT NULL,
  product TEXT NOT NULL,
  quantity INTEGER NOT NULL,
  limit_price REAL,
  notional_cap REAL NOT NULL,
  state TEXT NOT NULL,
  response_json TEXT NOT NULL DEFAULT '{}',
  decision_price REAL,
  decision_ts TEXT,
  submitted_at TEXT,
  acknowledged_at TEXT,
  execution_metrics_json TEXT NOT NULL DEFAULT '{}',
  margin_check_json TEXT NOT NULL DEFAULT '{}',
  cost_estimate_json TEXT NOT NULL DEFAULT '{}',
  position_reconcile_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(recommendation_id) REFERENCES recommendations(recommendation_id)
);

CREATE TABLE IF NOT EXISTS health_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  component TEXT NOT NULL,
  level TEXT NOT NULL,
  message TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS candidate_observations (
  book TEXT NOT NULL,
  period_key TEXT NOT NULL,
  symbol TEXT NOT NULL,
  side TEXT NOT NULL,
  observations INTEGER NOT NULL DEFAULT 0,
  avg_score REAL NOT NULL DEFAULT 0,
  max_score REAL NOT NULL DEFAULT 0,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY(book,period_key,symbol,side)
);
CREATE INDEX IF NOT EXISTS idx_candidate_obs ON candidate_observations(book,period_key,side,avg_score DESC);

CREATE TABLE IF NOT EXISTS feature_cache (
  symbol TEXT NOT NULL,
  timeframe TEXT NOT NULL,
  asof TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  PRIMARY KEY(symbol,timeframe)
);

CREATE TABLE IF NOT EXISTS fundamentals_cache (
  symbol TEXT PRIMARY KEY,
  asof TEXT NOT NULL,
  source TEXT NOT NULL,
  payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS system_state (
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS news_cache (
  symbol TEXT PRIMARY KEY,
  asof TEXT NOT NULL,
  payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trade_decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  decision_id TEXT NOT NULL UNIQUE,
  ts TEXT NOT NULL,
  book TEXT NOT NULL,
  period_key TEXT NOT NULL,
  symbol TEXT NOT NULL,
  side TEXT NOT NULL,
  decision TEXT NOT NULL,
  ensemble_score REAL,
  intelligence_score REAL,
  hard_fail_count INTEGER NOT NULL DEFAULT 0,
  strategy_ids_json TEXT NOT NULL DEFAULT '[]',
  payload_json TEXT NOT NULL DEFAULT '{}',
  audit_envelope_json TEXT NOT NULL DEFAULT '{}',
  pipeline_verdict TEXT,
  pipeline_stage TEXT,
  realized_outcome TEXT
);
CREATE INDEX IF NOT EXISTS idx_trade_decisions_book_ts ON trade_decisions(book,ts DESC);
CREATE INDEX IF NOT EXISTS idx_trade_decisions_symbol ON trade_decisions(symbol,side,ts DESC);


CREATE TABLE IF NOT EXISTS fundamental_snapshots (
  symbol TEXT NOT NULL,
  asof TEXT NOT NULL,
  source TEXT NOT NULL,
  payload_hash TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  PRIMARY KEY(symbol,asof)
);
CREATE INDEX IF NOT EXISTS idx_fund_snap_symbol_asof ON fundamental_snapshots(symbol,asof DESC);

CREATE TABLE IF NOT EXISTS market_events (
  event_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  title TEXT NOT NULL,
  starts_at TEXT NOT NULL,
  ends_at TEXT,
  impact TEXT NOT NULL DEFAULT 'MEDIUM',
  source TEXT NOT NULL,
  source_url TEXT,
  symbol TEXT,
  payload_json TEXT NOT NULL DEFAULT '{}',
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_market_events_time ON market_events(starts_at);
CREATE INDEX IF NOT EXISTS idx_market_events_symbol ON market_events(symbol,starts_at);

CREATE TABLE IF NOT EXISTS shadow_signals (
  shadow_id TEXT PRIMARY KEY,
  strategy_id TEXT NOT NULL,
  horizon TEXT NOT NULL,
  symbol TEXT NOT NULL,
  side TEXT NOT NULL,
  regime TEXT NOT NULL,
  score REAL NOT NULL,
  entry_price REAL NOT NULL,
  atr_pct REAL NOT NULL DEFAULT 0,
  opened_at TEXT NOT NULL,
  due_at TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'OPEN',
  exit_price REAL,
  resolved_at TEXT,
  return_pct REAL,
  r_multiple REAL,
  payload_json TEXT NOT NULL DEFAULT '{}',
  UNIQUE(strategy_id,symbol,side,opened_at),
  FOREIGN KEY(strategy_id) REFERENCES strategies(strategy_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_shadow_due ON shadow_signals(state,due_at);
CREATE INDEX IF NOT EXISTS idx_shadow_strategy ON shadow_signals(strategy_id,state);

CREATE TABLE IF NOT EXISTS order_fills (
  fill_key TEXT PRIMARY KEY,
  local_order_id TEXT NOT NULL,
  groww_order_id TEXT,
  quantity INTEGER NOT NULL DEFAULT 0,
  price REAL,
  trade_id TEXT,
  exchange_time TEXT,
  payload_json TEXT NOT NULL DEFAULT '{}',
  captured_at TEXT NOT NULL,
  FOREIGN KEY(local_order_id) REFERENCES orders(local_order_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_order_fills_local ON order_fills(local_order_id);

CREATE TABLE IF NOT EXISTS scan_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL UNIQUE,
  book TEXT NOT NULL,
  period_key TEXT,
  started_at TEXT NOT NULL,
  completed_at TEXT NOT NULL,
  status TEXT NOT NULL,
  universe_total INTEGER NOT NULL DEFAULT 0,
  scan_scope_total INTEGER NOT NULL DEFAULT 0,
  processed INTEGER NOT NULL DEFAULT 0,
  funnel_json TEXT NOT NULL DEFAULT '{}',
  near_misses_json TEXT NOT NULL DEFAULT '[]',
  payload_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_scan_runs_book_time ON scan_runs(book,completed_at DESC);

CREATE TABLE IF NOT EXISTS experiments (
  experiment_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  hypothesis TEXT NOT NULL,
  affected_books_json TEXT NOT NULL DEFAULT '[]',
  change_summary TEXT NOT NULL DEFAULT '',
  sample_requirement TEXT NOT NULL DEFAULT '',
  promotion_criterion TEXT NOT NULL DEFAULT '',
  rollback_criterion TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'PLANNED',
  release_version TEXT,
  started_at TEXT,
  ended_at TEXT,
  metrics_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_experiments_status ON experiments(status,started_at DESC);

CREATE TABLE IF NOT EXISTS institutional_snapshots (
  snapshot_id TEXT PRIMARY KEY,
  captured_at TEXT NOT NULL,
  source TEXT NOT NULL,
  payload_hash TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_institutional_time ON institutional_snapshots(captured_at DESC);

CREATE TABLE IF NOT EXISTS algorithm_versions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  algorithm_version TEXT NOT NULL,
  day TEXT NOT NULL,
  generated_at TEXT NOT NULL,
  manifest_hash TEXT NOT NULL,
  active_strategy_count INTEGER NOT NULL DEFAULT 0,
  accuracy_target REAL NOT NULL DEFAULT 0.80,
  observed_accuracy REAL,
  wilson_low REAL,
  wilson_high REAL,
  sample_size INTEGER NOT NULL DEFAULT 0,
  payload_json TEXT NOT NULL DEFAULT '{}',
  UNIQUE(day,algorithm_version)
);
CREATE INDEX IF NOT EXISTS idx_algorithm_versions_time ON algorithm_versions(generated_at DESC);

CREATE TABLE IF NOT EXISTS strategy_validation_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  strategy_id TEXT NOT NULL,
  validated_at TEXT NOT NULL,
  sample_count INTEGER NOT NULL,
  train_avg_r REAL,
  walk_avg_r REAL,
  holdout_avg_r REAL,
  cost_adjusted_avg_r REAL,
  parameter_stability REAL,
  multiple_testing_penalty REAL,
  promotion_eligible INTEGER NOT NULL DEFAULT 0,
  metrics_json TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY(strategy_id) REFERENCES strategies(strategy_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_validation_strategy ON strategy_validation_runs(strategy_id,validated_at DESC);
"""


def now_iso() -> str:
    return datetime.now(IST).isoformat(timespec="seconds")


def _connect(timeout_seconds: float = 10.0) -> sqlite3.Connection:
    timeout=max(0.5,float(timeout_seconds))
    con = sqlite3.connect(str(DB_PATH), timeout=timeout, isolation_level=None, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute(f"PRAGMA busy_timeout={int(timeout*1000)}")
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA synchronous=NORMAL")
    return con


def _ensure_columns(con: sqlite3.Connection) -> None:
    # SQLite CREATE TABLE IF NOT EXISTS does not add new columns to an existing v6 database.
    # Keep upgrades in-place and reversible by applying only additive migrations.
    cols = {r[1] for r in con.execute("PRAGMA table_info(strategy_stats)").fetchall()}
    additions = {
        "holdout_avg_r": "REAL",
        "cost_adjusted_avg_r": "REAL",
        "parameter_stability": "REAL",
        "multiple_testing_penalty": "REAL",
        "decay_state": "TEXT DEFAULT 'HEALTHY'",
    }
    for name, decl in additions.items():
        if name not in cols:
            con.execute(f"ALTER TABLE strategy_stats ADD COLUMN {name} {decl}")

    order_cols = {r[1] for r in con.execute("PRAGMA table_info(orders)").fetchall()}
    order_additions = {
        "filled_quantity": "INTEGER NOT NULL DEFAULT 0",
        "remaining_quantity": "INTEGER",
        "average_fill_price": "REAL",
        "broker_status_at": "TEXT",
        "reconciliation_json": "TEXT NOT NULL DEFAULT '{}'",
    }
    for name, decl in order_additions.items():
        if name not in order_cols:
            con.execute(f"ALTER TABLE orders ADD COLUMN {name} {decl}")

    rec_cols = {r[1] for r in con.execute("PRAGMA table_info(recommendations)").fetchall()}
    rec_additions = {
        "software_version": "TEXT",
        "config_hash": "TEXT",
        "decision_id": "TEXT",
        "audit_envelope_json": "TEXT NOT NULL DEFAULT '{}'",
    }
    for name, decl in rec_additions.items():
        if name not in rec_cols:
            con.execute(f"ALTER TABLE recommendations ADD COLUMN {name} {decl}")

    decision_cols = {r[1] for r in con.execute("PRAGMA table_info(trade_decisions)").fetchall()}
    decision_additions = {
        "audit_envelope_json": "TEXT NOT NULL DEFAULT '{}'",
        "pipeline_verdict": "TEXT",
        "pipeline_stage": "TEXT",
    }
    for name, decl in decision_additions.items():
        if name not in decision_cols:
            con.execute(f"ALTER TABLE trade_decisions ADD COLUMN {name} {decl}")

    order_cols = {r[1] for r in con.execute("PRAGMA table_info(orders)").fetchall()}
    v670_order_additions = {
        "decision_price": "REAL",
        "decision_ts": "TEXT",
        "submitted_at": "TEXT",
        "acknowledged_at": "TEXT",
        "execution_metrics_json": "TEXT NOT NULL DEFAULT '{}'",
        "margin_check_json": "TEXT NOT NULL DEFAULT '{}'",
        "cost_estimate_json": "TEXT NOT NULL DEFAULT '{}'",
        "position_reconcile_json": "TEXT NOT NULL DEFAULT '{}'",
    }
    for name, decl in v670_order_additions.items():
        if name not in order_cols:
            con.execute(f"ALTER TABLE orders ADD COLUMN {name} {decl}")


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as con:
        con.executescript(SCHEMA)
        _ensure_columns(con)


@contextmanager
def db(timeout_seconds: float = 10.0):
    """Return an independent short-lived SQLite connection.

    v6.3.7 deliberately does *not* wrap the whole context in a process-wide
    Python lock. SQLite WAL already permits concurrent readers and serializes
    writers with busy_timeout. The old RLock meant one background worker doing
    CPU/history work inside a db() context could freeze every scanner merely
    trying to read cached evidence or persist progress.
    """
    con = _connect(timeout_seconds)
    try:
        yield con
    finally:
        con.close()


def rows(sql: str, args: Iterable[Any] = ()) -> List[Dict[str, Any]]:
    with db() as con:
        return [dict(r) for r in con.execute(sql, tuple(args)).fetchall()]


def row(sql: str, args: Iterable[Any] = ()) -> Optional[Dict[str, Any]]:
    with db() as con:
        r = con.execute(sql, tuple(args)).fetchone()
        return dict(r) if r else None


def execute(sql: str, args: Iterable[Any] = ()) -> int:
    with db() as con:
        cur = con.execute(sql, tuple(args))
        return cur.rowcount


def set_state(key: str, value: Any) -> bool:
    """Persist telemetry without allowing a transient SQLite write lock to kill a worker.

    system_state is operational telemetry, not the recommendation ledger. A temporary
    lock must never terminate a domain worker. Locked/busy writes are retried briefly;
    storage I/O/full errors fail soft so the supervisor can keep the process alive and
    the next cycle can recover after disk pressure is resolved.
    """
    payload=(key, json.dumps(value, separators=(",", ":"), default=str), now_iso())
    for attempt in range(6):
        try:
            with db() as con:
                con.execute(
                    "INSERT INTO system_state(key,value_json,updated_at) VALUES(?,?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at",
                    payload,
                )
            return True
        except sqlite3.OperationalError as exc:
            msg=str(exc).lower()
            if ("locked" in msg or "busy" in msg) and attempt < 5:
                time.sleep(0.05 * (attempt + 1))
                continue
            return False
        except sqlite3.Error:
            return False
    return False


def get_state(key: str, default: Any = None) -> Any:
    r = row("SELECT value_json FROM system_state WHERE key=?", (key,))
    if not r:
        return default
    try:
        return json.loads(r["value_json"])
    except Exception:
        return default


def health(component: str, level: str, message: str, payload: Optional[Dict[str, Any]] = None) -> bool:
    """Best-effort health logging.

    Error reporting must not raise a second SQLite exception and terminate the worker
    that was trying to report the first failure.
    """
    for attempt in range(4):
        try:
            with db() as con:
                con.execute(
                    "INSERT INTO health_events(ts,component,level,message,payload_json) VALUES(?,?,?,?,?)",
                    (now_iso(), component, level, message, json.dumps(payload or {}, separators=(",", ":"), default=str)),
                )
                con.execute(
                    "DELETE FROM health_events WHERE id NOT IN (SELECT id FROM health_events ORDER BY id DESC LIMIT 2000)"
                )
            return True
        except sqlite3.OperationalError as exc:
            msg=str(exc).lower()
            if ("locked" in msg or "busy" in msg) and attempt < 3:
                time.sleep(0.05 * (attempt + 1))
                continue
            return False
        except sqlite3.Error:
            return False
    return False
