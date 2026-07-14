from __future__ import annotations

import json
import math
import os
import sqlite3
import sys
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _default_db_path() -> Path:
    configured = os.getenv("TRADER_DB_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "SuhasPrivateAITrader" / "trader.db"
    return ROOT / ".runtime" / "trader.db"


class MemoryStore:
    """Thread-safe local SQLite memory. It never stores broker credentials."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else _default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        try:
            yield connection
        finally:
            connection.close()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)

    def _initialize(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS news_articles(
          id TEXT PRIMARY KEY, symbol TEXT NOT NULL, title TEXT NOT NULL, url TEXT NOT NULL,
          source TEXT, published_at TEXT, fetched_at TEXT NOT NULL, sentiment REAL NOT NULL,
          payload_json TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_news_symbol_time ON news_articles(symbol,fetched_at DESC);
        CREATE TABLE IF NOT EXISTS news_embeddings(
          article_id TEXT PRIMARY KEY REFERENCES news_articles(id) ON DELETE CASCADE,
          model TEXT NOT NULL, vector_json TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS pattern_snapshots(
          symbol TEXT NOT NULL, exchange TEXT NOT NULL, as_of_date TEXT NOT NULL,
          score REAL NOT NULL, label TEXT, data_json TEXT NOT NULL, created_at TEXT NOT NULL,
          PRIMARY KEY(symbol,exchange,as_of_date));
        CREATE TABLE IF NOT EXISTS price_snapshots(
          symbol TEXT NOT NULL, exchange TEXT NOT NULL, ts TEXT NOT NULL,
          price REAL NOT NULL, source TEXT NOT NULL, PRIMARY KEY(symbol,exchange,ts));
        CREATE INDEX IF NOT EXISTS idx_price_symbol_time ON price_snapshots(symbol,ts DESC);
        CREATE TABLE IF NOT EXISTS signal_snapshots(
          signal_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, exchange TEXT NOT NULL,
          state TEXT NOT NULL, action TEXT NOT NULL, generated_at TEXT NOT NULL,
          entry_price REAL, target_price REAL, stop_loss REAL, last_price REAL, confidence REAL,
          agent_scores_json TEXT NOT NULL, payload_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS signal_outcomes(
          id TEXT PRIMARY KEY, signal_id TEXT NOT NULL REFERENCES signal_snapshots(signal_id) ON DELETE CASCADE,
          horizon_minutes INTEGER NOT NULL, observed_at TEXT NOT NULL, observed_price REAL NOT NULL,
          return_pct REAL NOT NULL, target_hit INTEGER NOT NULL, stop_hit INTEGER NOT NULL,
          outcome TEXT NOT NULL, UNIQUE(signal_id,horizon_minutes));
        CREATE TABLE IF NOT EXISTS agent_stats(
          agent TEXT PRIMARY KEY, resolved_count INTEGER NOT NULL, correct_count INTEGER NOT NULL,
          accuracy REAL NOT NULL, weight_multiplier REAL NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS llm_analyses(
          id TEXT PRIMARY KEY, symbol TEXT, event_type TEXT NOT NULL, event_key TEXT NOT NULL UNIQUE,
          created_at TEXT NOT NULL, model TEXT NOT NULL, analysis TEXT NOT NULL, payload_json TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS provider_health(
          provider TEXT PRIMARY KEY, status TEXT NOT NULL, last_success_at TEXT, last_failure_at TEXT,
          consecutive_failures INTEGER NOT NULL, latency_ms REAL, message TEXT, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS exit_signals(
          id TEXT PRIMARY KEY, symbol TEXT NOT NULL, created_at TEXT NOT NULL, action TEXT NOT NULL,
          urgency TEXT NOT NULL, pnl_pct REAL, reason TEXT NOT NULL, payload_json TEXT NOT NULL);
        """
        with self._lock, self.connect() as connection:
            connection.executescript(schema)

    def store_pattern(self, pattern: dict[str, Any]) -> None:
        symbol = str(pattern.get("symbol") or "").upper()
        if not symbol:
            return
        exchange = str(pattern.get("exchange") or "NSE").upper()
        as_of = str(pattern.get("as_of_date") or datetime.now(timezone.utc).date().isoformat())
        with self._lock, self.connect() as connection:
            connection.execute(
                """INSERT INTO pattern_snapshots(symbol,exchange,as_of_date,score,label,data_json,created_at)
                   VALUES(?,?,?,?,?,?,?) ON CONFLICT(symbol,exchange,as_of_date) DO UPDATE SET
                   score=excluded.score,label=excluded.label,data_json=excluded.data_json,created_at=excluded.created_at""",
                (symbol, exchange, as_of, float(pattern.get("score") or 0), str(pattern.get("label") or ""), self._json(pattern), self._now()),
            )

    def latest_pattern(self, symbol: str, exchange: str = "NSE") -> dict[str, Any] | None:
        with self._lock, self.connect() as connection:
            row = connection.execute(
                "SELECT data_json FROM pattern_snapshots WHERE symbol=? AND exchange=? ORDER BY as_of_date DESC LIMIT 1",
                (symbol.upper(), exchange.upper()),
            ).fetchone()
        return json.loads(row["data_json"]) if row else None

    def store_news_result(self, result: dict[str, Any], sentiment_fn) -> list[dict[str, Any]]:
        symbol = str(result.get("symbol") or "").upper()
        now = self._now()
        new_items: list[dict[str, Any]] = []
        with self._lock, self.connect() as connection:
            for item in result.get("headlines") or []:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title") or "").strip()
                url = str(item.get("url") or "").strip()
                if not symbol or not title or not url:
                    continue
                article_id = uuid.uuid5(uuid.NAMESPACE_URL, f"{symbol}:{url}").hex
                sentiment = float(sentiment_fn(title))
                cursor = connection.execute(
                    """INSERT OR IGNORE INTO news_articles
                       (id,symbol,title,url,source,published_at,fetched_at,sentiment,payload_json)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (article_id, symbol, title, url, str(item.get("source") or ""), str(item.get("published") or ""), now, sentiment, self._json(item)),
                )
                if cursor.rowcount:
                    enriched = dict(item)
                    enriched.update({"article_id": article_id, "sentiment": sentiment})
                    new_items.append(enriched)
        return new_items

    def recent_news(self, symbol: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        sql = "SELECT * FROM news_articles"
        params: list[Any] = []
        if symbol:
            sql += " WHERE symbol=?"
            params.append(symbol.upper())
        sql += " ORDER BY fetched_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 500)))
        with self._lock, self.connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [dict(row) | {"payload": json.loads(row["payload_json"])} for row in rows]

    def store_embedding(self, article_id: str, model: str, vector: list[float]) -> None:
        with self._lock, self.connect() as connection:
            connection.execute(
                """INSERT INTO news_embeddings(article_id,model,vector_json,created_at) VALUES(?,?,?,?)
                   ON CONFLICT(article_id) DO UPDATE SET model=excluded.model,vector_json=excluded.vector_json,created_at=excluded.created_at""",
                (article_id, model, self._json(vector), self._now()),
            )

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        if not left or len(left) != len(right):
            return 0.0
        dot = sum(a * b for a, b in zip(left, right))
        denom = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
        return dot / denom if denom else 0.0

    def similar_news(self, vector: list[float], *, symbol: str | None = None, limit: int = 5) -> list[dict[str, Any]]:
        sql = """SELECT n.*,e.vector_json,e.model FROM news_embeddings e
                 JOIN news_articles n ON n.id=e.article_id"""
        params: list[Any] = []
        if symbol:
            sql += " WHERE n.symbol=?"
            params.append(symbol.upper())
        sql += " ORDER BY n.fetched_at DESC LIMIT 500"
        with self._lock, self.connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        scored = []
        for row in rows:
            item = dict(row)
            similarity = self._cosine(vector, [float(v) for v in json.loads(row["vector_json"])])
            item["similarity"] = round(similarity, 6)
            item.pop("vector_json", None)
            scored.append(item)
        scored.sort(key=lambda item: item["similarity"], reverse=True)
        return scored[: max(1, min(int(limit), 20))]

    def store_price(self, symbol: str, exchange: str, price: float, source: str, ts: str | None = None) -> None:
        if price <= 0:
            return
        with self._lock, self.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO price_snapshots(symbol,exchange,ts,price,source) VALUES(?,?,?,?,?)",
                (symbol.upper(), exchange.upper(), ts or self._now(), float(price), source),
            )

    def record_signal(self, signal: dict[str, Any]) -> bool:
        signal_id = str(signal.get("recommendation_id") or signal.get("signal_id") or "").strip()
        symbol = str(signal.get("symbol") or "").upper()
        if not signal_id or not symbol:
            return False
        with self._lock, self.connect() as connection:
            cursor = connection.execute(
                """INSERT OR IGNORE INTO signal_snapshots
                   (signal_id,symbol,exchange,state,action,generated_at,entry_price,target_price,stop_loss,last_price,confidence,agent_scores_json,payload_json)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    signal_id, symbol, str(signal.get("exchange") or "NSE").upper(), str(signal.get("state") or "WAIT"),
                    str(signal.get("action") or signal.get("state") or "WAIT"), str(signal.get("generated_at") or self._now()),
                    signal.get("entry_price"), signal.get("target_price"), signal.get("stop_loss"), signal.get("last_price"), signal.get("confidence"),
                    self._json(signal.get("agent_scores") or {}), self._json(signal),
                ),
            )
        return bool(cursor.rowcount)

    def due_signals(self, horizon_minutes: int, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock, self.connect() as connection:
            rows = connection.execute(
                """SELECT s.* FROM signal_snapshots s LEFT JOIN signal_outcomes o
                   ON o.signal_id=s.signal_id AND o.horizon_minutes=?
                   WHERE o.id IS NULL AND (julianday('now')-julianday(s.generated_at))*1440 >= ?
                   ORDER BY s.generated_at LIMIT ?""",
                (int(horizon_minutes), int(horizon_minutes), max(1, min(int(limit), 1000))),
            ).fetchall()
        return [dict(row) for row in rows]

    def record_outcome(self, signal: dict[str, Any], horizon_minutes: int, observed_price: float) -> dict[str, Any]:
        entry = float(signal.get("entry_price") or signal.get("last_price") or 0)
        if entry <= 0 or observed_price <= 0:
            return {}
        target = float(signal.get("target_price") or 0)
        stop = float(signal.get("stop_loss") or 0)
        return_pct = (observed_price - entry) / entry * 100
        target_hit = target > 0 and observed_price >= target
        stop_hit = stop > 0 and observed_price <= stop
        outcome = "TARGET" if target_hit else "STOP" if stop_hit else "POSITIVE" if return_pct > 0 else "NEGATIVE" if return_pct < 0 else "FLAT"
        outcome_id = uuid.uuid5(uuid.NAMESPACE_URL, f"{signal['signal_id']}:{horizon_minutes}").hex
        with self._lock, self.connect() as connection:
            cursor = connection.execute(
                """INSERT OR IGNORE INTO signal_outcomes
                   (id,signal_id,horizon_minutes,observed_at,observed_price,return_pct,target_hit,stop_hit,outcome)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (outcome_id, signal["signal_id"], int(horizon_minutes), self._now(), float(observed_price), return_pct, int(target_hit), int(stop_hit), outcome),
            )
        if cursor.rowcount:
            self._update_agent_stats(json.loads(signal.get("agent_scores_json") or "{}"), return_pct > 0)
        return {"signal_id": signal["signal_id"], "horizon_minutes": int(horizon_minutes), "observed_price": observed_price, "return_pct": round(return_pct, 4), "outcome": outcome}

    def _update_agent_stats(self, scores: dict[str, Any], positive_outcome: bool) -> None:
        now = self._now()
        with self._lock, self.connect() as connection:
            for agent, raw_score in scores.items():
                try:
                    predicted_positive = float(raw_score) >= 50
                except (TypeError, ValueError):
                    continue
                correct = int(predicted_positive == positive_outcome)
                row = connection.execute("SELECT resolved_count,correct_count FROM agent_stats WHERE agent=?", (agent,)).fetchone()
                resolved = int(row["resolved_count"] if row else 0) + 1
                correct_count = int(row["correct_count"] if row else 0) + correct
                accuracy = correct_count / resolved
                multiplier = 1.0 if resolved < 10 else max(0.75, min(1.25, 0.75 + accuracy))
                connection.execute(
                    """INSERT INTO agent_stats(agent,resolved_count,correct_count,accuracy,weight_multiplier,updated_at)
                       VALUES(?,?,?,?,?,?) ON CONFLICT(agent) DO UPDATE SET
                       resolved_count=excluded.resolved_count,correct_count=excluded.correct_count,accuracy=excluded.accuracy,
                       weight_multiplier=excluded.weight_multiplier,updated_at=excluded.updated_at""",
                    (agent, resolved, correct_count, accuracy, multiplier, now),
                )

    def agent_weight_multipliers(self) -> dict[str, float]:
        with self._lock, self.connect() as connection:
            rows = connection.execute("SELECT agent,weight_multiplier FROM agent_stats").fetchall()
        return {str(row["agent"]): float(row["weight_multiplier"]) for row in rows}

    def agent_stats(self) -> list[dict[str, Any]]:
        with self._lock, self.connect() as connection:
            rows = connection.execute("SELECT * FROM agent_stats ORDER BY resolved_count DESC,agent").fetchall()
        return [dict(row) for row in rows]

    def has_llm_event(self, event_key: str) -> bool:
        with self._lock, self.connect() as connection:
            return connection.execute("SELECT 1 FROM llm_analyses WHERE event_key=?", (event_key,)).fetchone() is not None

    def store_llm_analysis(self, *, symbol: str | None, event_type: str, event_key: str, model: str, analysis: str, payload: dict[str, Any]) -> dict[str, Any]:
        item = {"id": uuid.uuid5(uuid.NAMESPACE_URL, event_key).hex, "symbol": symbol.upper() if symbol else None, "event_type": event_type, "event_key": event_key, "created_at": self._now(), "model": model, "analysis": analysis, "payload": payload}
        with self._lock, self.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO llm_analyses(id,symbol,event_type,event_key,created_at,model,analysis,payload_json) VALUES(?,?,?,?,?,?,?,?)",
                (item["id"], item["symbol"], event_type, event_key, item["created_at"], model, analysis, self._json(payload)),
            )
        return item

    def recent_llm_analyses(self, limit: int = 25) -> list[dict[str, Any]]:
        with self._lock, self.connect() as connection:
            rows = connection.execute("SELECT * FROM llm_analyses ORDER BY created_at DESC LIMIT ?", (max(1, min(int(limit), 100)),)).fetchall()
        return [dict(row) | {"payload": json.loads(row["payload_json"])} for row in rows]

    def update_provider_health(self, provider: str, *, ok: bool, latency_ms: float | None = None, message: str = "") -> None:
        now = self._now()
        with self._lock, self.connect() as connection:
            row = connection.execute("SELECT * FROM provider_health WHERE provider=?", (provider,)).fetchone()
            failures = 0 if ok else int(row["consecutive_failures"] if row else 0) + 1
            status = "healthy" if ok else "degraded" if failures < 3 else "unavailable"
            last_success = now if ok else (row["last_success_at"] if row else None)
            last_failure = now if not ok else (row["last_failure_at"] if row else None)
            connection.execute(
                """INSERT INTO provider_health(provider,status,last_success_at,last_failure_at,consecutive_failures,latency_ms,message,updated_at)
                   VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(provider) DO UPDATE SET status=excluded.status,last_success_at=excluded.last_success_at,
                   last_failure_at=excluded.last_failure_at,consecutive_failures=excluded.consecutive_failures,latency_ms=excluded.latency_ms,
                   message=excluded.message,updated_at=excluded.updated_at""",
                (provider, status, last_success, last_failure, failures, latency_ms, message[:500], now),
            )

    def provider_health(self) -> list[dict[str, Any]]:
        with self._lock, self.connect() as connection:
            rows = connection.execute("SELECT * FROM provider_health ORDER BY provider").fetchall()
        return [dict(row) for row in rows]

    def store_exit_signal(self, signal: dict[str, Any]) -> None:
        symbol = str(signal.get("symbol") or "").upper()
        if not symbol:
            return
        event_key = f"{symbol}:{signal.get('action')}:{signal.get('created_at')}"
        with self._lock, self.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO exit_signals(id,symbol,created_at,action,urgency,pnl_pct,reason,payload_json) VALUES(?,?,?,?,?,?,?,?)",
                (uuid.uuid5(uuid.NAMESPACE_URL, event_key).hex, symbol, signal.get("created_at") or self._now(), str(signal.get("action") or "HOLD"), str(signal.get("urgency") or "normal"), signal.get("pnl_pct"), str(signal.get("reason") or ""), self._json(signal)),
            )

    def backup(self, destination: Path | str | None = None) -> str:
        if destination is None:
            backup_dir = self.path.parent / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            destination_path = backup_dir / f"trader-{datetime.now(timezone.utc).date().isoformat()}.db"
        else:
            destination_path = Path(destination).expanduser()
            destination_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self.connect() as source:
            target = sqlite3.connect(destination_path)
            try:
                source.backup(target)
            finally:
                target.close()
        return str(destination_path)

    def prune(self, *, price_retention_days: int = 30, news_retention_days: int = 365, llm_retention_days: int = 180) -> dict[str, int]:
        deleted: dict[str, int] = {}
        with self._lock, self.connect() as connection:
            for key, sql, days in (
                ("price_snapshots", "DELETE FROM price_snapshots WHERE julianday('now')-julianday(ts) > ?", price_retention_days),
                ("news_articles", "DELETE FROM news_articles WHERE julianday('now')-julianday(fetched_at) > ?", news_retention_days),
                ("llm_analyses", "DELETE FROM llm_analyses WHERE julianday('now')-julianday(created_at) > ?", llm_retention_days),
            ):
                cursor = connection.execute(sql, (int(days),))
                deleted[key] = max(0, cursor.rowcount)
        return deleted

    def stats(self) -> dict[str, Any]:
        tables = ("news_articles", "pattern_snapshots", "price_snapshots", "signal_snapshots", "signal_outcomes", "llm_analyses", "exit_signals")
        result: dict[str, Any] = {"path": str(self.path)}
        with self._lock, self.connect() as connection:
            for table in tables:
                result[table] = int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        return result
