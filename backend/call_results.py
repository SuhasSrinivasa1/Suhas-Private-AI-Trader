from __future__ import annotations

import asyncio
import json
import math
import os
import uuid
from datetime import datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from groww_adapter import get_ltp_batch_sync

IST = ZoneInfo("Asia/Kolkata")
PAPER_OBSERVATION_DAYS = max(1, int(os.getenv("PAPER_OBSERVATION_DAYS", "7")))
RESOLUTION_INTERVAL_SECONDS = max(5, int(os.getenv("CALL_RESOLUTION_INTERVAL_SECONDS", "15")))
INTRADAY_DEDUP_MINUTES = max(5, int(os.getenv("INTRADAY_CALL_DEDUP_MINUTES", "30")))
DELIVERY_DEDUP_MINUTES = max(60, int(os.getenv("DELIVERY_CALL_DEDUP_MINUTES", "1440")))
DELIVERY_HORIZON_DAYS = max(1, int(os.getenv("DELIVERY_CALL_HORIZON_DAYS", "7")))
TARGET_PRECISION = max(0.50, min(0.999, float(os.getenv("CALL_TARGET_PRECISION", "0.99"))))
MIN_CALIBRATION_SAMPLES = max(20, int(os.getenv("CALL_MIN_CALIBRATION_SAMPLES", "50")))
MIN_CONFIDENCE = max(50.0, min(95.0, float(os.getenv("CALL_CONFIDENCE_MIN", "72"))))
MAX_CONFIDENCE = max(MIN_CONFIDENCE, min(99.0, float(os.getenv("CALL_CONFIDENCE_MAX", "95"))))


class CallResultsEngine:
    """Paper-call ledger, deterministic result resolution and bounded precision calibration."""

    def __init__(self, core: Any, runtime: Any, overlay: Any) -> None:
        self.core = core
        self.runtime = runtime
        self.overlay = overlay
        self.store = runtime.store
        self._last_broadcast_signature = ""
        self._initialize()

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _iso(value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat()

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)

    def _initialize(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS paper_calls(
          id TEXT PRIMARY KEY,
          recommendation_id TEXT NOT NULL,
          symbol TEXT NOT NULL,
          exchange TEXT NOT NULL,
          trading_mode TEXT NOT NULL,
          call_type TEXT NOT NULL,
          predicted_buy_price REAL NOT NULL,
          predicted_sell_price REAL NOT NULL,
          stop_loss REAL NOT NULL,
          confidence REAL NOT NULL,
          consensus_score REAL NOT NULL,
          predicted_at TEXT NOT NULL,
          evaluation_deadline TEXT NOT NULL,
          status TEXT NOT NULL,
          result_reason TEXT,
          resolved_at TEXT,
          resolved_price REAL,
          return_pct REAL,
          highest_price REAL NOT NULL,
          lowest_price REAL NOT NULL,
          observation_count INTEGER NOT NULL,
          decision_model TEXT,
          agent_scores_json TEXT NOT NULL,
          payload_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_paper_calls_time ON paper_calls(predicted_at DESC);
        CREATE INDEX IF NOT EXISTS idx_paper_calls_status ON paper_calls(status,evaluation_deadline);
        CREATE INDEX IF NOT EXISTS idx_paper_calls_symbol_mode ON paper_calls(symbol,trading_mode,predicted_at DESC);
        CREATE TABLE IF NOT EXISTS call_learning_meta(
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        """
        with self.store._lock, self.store.connect() as connection:
            connection.executescript(schema)
            row = connection.execute("SELECT value FROM call_learning_meta WHERE key='observation_started_at'").fetchone()
            if row is None:
                now = self._iso(self._now())
                connection.execute(
                    "INSERT INTO call_learning_meta(key,value,updated_at) VALUES('observation_started_at',?,?)",
                    (now, now),
                )

    def observation_status(self) -> dict[str, Any]:
        with self.store._lock, self.store.connect() as connection:
            row = connection.execute("SELECT value FROM call_learning_meta WHERE key='observation_started_at'").fetchone()
        started = datetime.fromisoformat(str(row["value"])) if row else self._now()
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        ends = started + timedelta(days=PAPER_OBSERVATION_DAYS)
        remaining = max(0.0, (ends - self._now()).total_seconds())
        return {
            "started_at": self._iso(started),
            "ends_at": self._iso(ends),
            "observation_days": PAPER_OBSERVATION_DAYS,
            "remaining_seconds": int(remaining),
            "remaining_days": round(remaining / 86400, 2),
            "complete": remaining <= 0,
            "paper_calls_only": remaining > 0,
            "live_orders_blocked": remaining > 0,
        }

    def _deadline(self, mode: str, predicted_at: datetime) -> datetime:
        if mode == "delivery":
            return predicted_at + timedelta(days=DELIVERY_HORIZON_DAYS)
        local = predicted_at.astimezone(IST)
        deadline_local = datetime.combine(local.date(), time(15, 25), tzinfo=IST)
        if deadline_local <= local:
            deadline_local = local + timedelta(minutes=30)
        return deadline_local.astimezone(timezone.utc)

    def _dedup_minutes(self, mode: str) -> int:
        return DELIVERY_DEDUP_MINUTES if mode == "delivery" else INTRADAY_DEDUP_MINUTES

    def record_prediction(self, result: dict[str, Any]) -> dict[str, Any] | None:
        if str(result.get("state") or "").upper() != "BUY":
            return None
        symbol = str(result.get("symbol") or "").upper().strip()
        mode = str(result.get("trading_mode") or self.overlay.mode or "intraday").lower()
        entry = float(result.get("entry_price") or result.get("last_price") or 0)
        target = float(result.get("target_price") or 0)
        stop = float(result.get("stop_loss") or 0)
        confidence = float(result.get("confidence") or 0)
        consensus = float(result.get("agent_consensus_score") or 0)
        recommendation_id = str(result.get("recommendation_id") or "").strip()
        if not symbol or not recommendation_id or entry <= 0 or target <= entry or stop <= 0 or stop >= entry:
            return None
        now = self._now()
        cutoff = now - timedelta(minutes=self._dedup_minutes(mode))
        with self.store._lock, self.store.connect() as connection:
            duplicate = connection.execute(
                """SELECT id FROM paper_calls WHERE symbol=? AND trading_mode=? AND predicted_at>=?
                   AND status='OPEN' ORDER BY predicted_at DESC LIMIT 1""",
                (symbol, mode, self._iso(cutoff)),
            ).fetchone()
            if duplicate:
                return None
            call_id = uuid.uuid5(uuid.NAMESPACE_URL, f"paper-call:{recommendation_id}:{mode}").hex
            agents = result.get("specialist_agents") or result.get("agent_scores") or {}
            agent_scores = {
                key: (value.get("score") if isinstance(value, dict) else value)
                for key, value in agents.items()
            }
            connection.execute(
                """INSERT OR IGNORE INTO paper_calls(
                   id,recommendation_id,symbol,exchange,trading_mode,call_type,predicted_buy_price,predicted_sell_price,
                   stop_loss,confidence,consensus_score,predicted_at,evaluation_deadline,status,result_reason,resolved_at,
                   resolved_price,return_pct,highest_price,lowest_price,observation_count,decision_model,agent_scores_json,payload_json)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'OPEN',NULL,NULL,NULL,NULL,?,?,0,?,?,?)""",
                (
                    call_id,
                    recommendation_id,
                    symbol,
                    str(result.get("exchange") or "NSE").upper(),
                    mode,
                    "BUY_TO_SELL_TARGET",
                    entry,
                    target,
                    stop,
                    confidence,
                    consensus,
                    self._iso(now),
                    self._iso(self._deadline(mode, now)),
                    entry,
                    entry,
                    str(result.get("decision_model") or ""),
                    self._json(agent_scores),
                    self._json(result),
                ),
            )
        return self.call_by_id(call_id)

    def call_by_id(self, call_id: str) -> dict[str, Any] | None:
        with self.store._lock, self.store.connect() as connection:
            row = connection.execute("SELECT * FROM paper_calls WHERE id=?", (call_id,)).fetchone()
        return self._row(row) if row else None

    @staticmethod
    def _row(row: Any) -> dict[str, Any]:
        item = dict(row)
        for source, target in (("agent_scores_json", "agent_scores"), ("payload_json", "payload")):
            try:
                item[target] = json.loads(item.get(source) or "{}")
            except json.JSONDecodeError:
                item[target] = {}
            item.pop(source, None)
        item["correct"] = True if item.get("status") == "CORRECT" else False if item.get("status") == "WRONG" else None
        return item

    def open_calls(self, limit: int = 1000) -> list[dict[str, Any]]:
        with self.store._lock, self.store.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM paper_calls WHERE status='OPEN' ORDER BY predicted_at LIMIT ?",
                (max(1, min(int(limit), 5000)),),
            ).fetchall()
        return [self._row(row) for row in rows]

    def list_calls(self, *, limit: int = 250, mode: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if mode in {"intraday", "delivery"}:
            clauses.append("trading_mode=?")
            params.append(mode)
        if status in {"OPEN", "CORRECT", "WRONG"}:
            clauses.append("status=?")
            params.append(status)
        sql = "SELECT * FROM paper_calls"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY predicted_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 2000)))
        with self.store._lock, self.store.connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [self._row(row) for row in rows]

    def observe_price(self, call_id: str, price: float, observed_at: datetime | None = None) -> dict[str, Any] | None:
        if price <= 0:
            return None
        observed = observed_at or self._now()
        with self.store._lock, self.store.connect() as connection:
            row = connection.execute("SELECT * FROM paper_calls WHERE id=?", (call_id,)).fetchone()
            if row is None or row["status"] != "OPEN":
                return None
            item = dict(row)
            high = max(float(item["highest_price"]), float(price))
            low = min(float(item["lowest_price"]), float(price))
            target = float(item["predicted_sell_price"])
            stop = float(item["stop_loss"])
            entry = float(item["predicted_buy_price"])
            deadline = datetime.fromisoformat(str(item["evaluation_deadline"]))
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)
            status = "OPEN"
            reason = None
            if price >= target:
                status, reason = "CORRECT", "predicted_sell_target_reached_before_stop"
            elif price <= stop:
                status, reason = "WRONG", "stop_reached_before_predicted_sell_target"
            elif observed >= deadline:
                status, reason = "WRONG", "evaluation_window_expired_before_predicted_sell_target"
            resolved_at = self._iso(observed) if status != "OPEN" else None
            return_pct = ((float(price) - entry) / entry) * 100
            connection.execute(
                """UPDATE paper_calls SET highest_price=?,lowest_price=?,observation_count=observation_count+1,
                   status=?,result_reason=?,resolved_at=?,resolved_price=?,return_pct=? WHERE id=?""",
                (high, low, status, reason, resolved_at, float(price) if status != "OPEN" else None, return_pct if status != "OPEN" else None, call_id),
            )
        if status != "OPEN":
            try:
                scores = json.loads(item.get("agent_scores_json") or "{}")
                self.store._update_agent_stats(scores, status == "CORRECT")
            except Exception:
                pass
        updated = self.call_by_id(call_id)
        return updated if status != "OPEN" else None

    @staticmethod
    def _wilson_lower(correct: int, total: int, z: float = 1.96) -> float:
        if total <= 0:
            return 0.0
        p = correct / total
        denominator = 1 + z * z / total
        centre = p + z * z / (2 * total)
        margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total)
        return max(0.0, (centre - margin) / denominator)

    def learning_profile(self) -> dict[str, Any]:
        observation = self.observation_status()
        with self.store._lock, self.store.connect() as connection:
            rows = connection.execute(
                "SELECT confidence,status FROM paper_calls WHERE status IN ('CORRECT','WRONG') ORDER BY predicted_at"
            ).fetchall()
        resolved = len(rows)
        base_correct = sum(1 for row in rows if row["status"] == "CORRECT")
        selected_threshold = MIN_CONFIDENCE
        selected_accuracy = (base_correct / resolved) if resolved else 0.0
        selected_lower_bound = self._wilson_lower(base_correct, resolved)
        best_key = (selected_lower_bound, selected_accuracy, resolved, -selected_threshold)
        for threshold in range(int(math.ceil(MIN_CONFIDENCE)), int(math.floor(MAX_CONFIDENCE)) + 1):
            filtered = [row for row in rows if float(row["confidence"] or 0) >= threshold]
            if len(filtered) < MIN_CALIBRATION_SAMPLES:
                continue
            correct = sum(1 for row in filtered if row["status"] == "CORRECT")
            accuracy = correct / len(filtered)
            lower = self._wilson_lower(correct, len(filtered))
            key = (lower, accuracy, len(filtered), -threshold)
            if key > best_key:
                best_key = key
                selected_threshold = float(threshold)
                selected_accuracy = accuracy
                selected_lower_bound = lower
        if not observation["complete"]:
            state = "collecting_first_week"
        elif resolved < MIN_CALIBRATION_SAMPLES:
            state = "insufficient_resolved_calls"
        elif selected_accuracy >= TARGET_PRECISION:
            state = "target_observed_not_guaranteed"
        else:
            state = "precision_calibrating"
        return {
            "state": state,
            "target_precision": TARGET_PRECISION,
            "target_precision_pct": round(TARGET_PRECISION * 100, 2),
            "target_is_guaranteed": False,
            "resolved_calls": resolved,
            "minimum_samples": MIN_CALIBRATION_SAMPLES,
            "recommended_min_confidence": round(selected_threshold, 2),
            "observed_accuracy": round(selected_accuracy, 6),
            "observed_accuracy_pct": round(selected_accuracy * 100, 2),
            "wilson_lower_bound": round(selected_lower_bound, 6),
            "automatic_calibration": True,
            "risk_rules_may_only_tighten": True,
            "observation": observation,
            "note": "The system automatically calibrates toward higher precision by becoming more selective. No accuracy percentage, including 99%, is guaranteed.",
        }

    def summary(self) -> dict[str, Any]:
        with self.store._lock, self.store.connect() as connection:
            totals = connection.execute(
                """SELECT COUNT(*) total,
                   SUM(CASE WHEN status='OPEN' THEN 1 ELSE 0 END) open_count,
                   SUM(CASE WHEN status='CORRECT' THEN 1 ELSE 0 END) correct_count,
                   SUM(CASE WHEN status='WRONG' THEN 1 ELSE 0 END) wrong_count
                   FROM paper_calls"""
            ).fetchone()
            modes = connection.execute(
                """SELECT trading_mode,COUNT(*) total,
                   SUM(CASE WHEN status='CORRECT' THEN 1 ELSE 0 END) correct_count,
                   SUM(CASE WHEN status='WRONG' THEN 1 ELSE 0 END) wrong_count
                   FROM paper_calls GROUP BY trading_mode ORDER BY trading_mode"""
            ).fetchall()
            daily = connection.execute(
                """SELECT substr(predicted_at,1,10) day,COUNT(*) total,
                   SUM(CASE WHEN status='CORRECT' THEN 1 ELSE 0 END) correct_count,
                   SUM(CASE WHEN status='WRONG' THEN 1 ELSE 0 END) wrong_count
                   FROM paper_calls GROUP BY substr(predicted_at,1,10) ORDER BY day DESC LIMIT 14"""
            ).fetchall()
        total = int(totals["total"] or 0)
        open_count = int(totals["open_count"] or 0)
        correct = int(totals["correct_count"] or 0)
        wrong = int(totals["wrong_count"] or 0)
        resolved = correct + wrong
        accuracy = correct / resolved if resolved else 0.0
        return {
            "total_calls": total,
            "open_calls": open_count,
            "resolved_calls": resolved,
            "correct_calls": correct,
            "wrong_calls": wrong,
            "accuracy": round(accuracy, 6),
            "accuracy_pct": round(accuracy * 100, 2),
            "correct_definition": "Predicted sell target reached before stop loss and before the mode-specific evaluation deadline.",
            "predictions_are_paper_calls_not_trades": True,
            "modes": [dict(row) for row in modes],
            "daily": [dict(row) for row in reversed(daily)],
            "observation": self.observation_status(),
            "learning": self.learning_profile(),
        }

    async def resolve_once(self) -> list[dict[str, Any]]:
        calls = self.open_calls()
        if not calls:
            return []
        symbol_prices: dict[str, float] = {}
        for call in calls:
            symbol = str(call["symbol"])
            snapshot = self.core.latest_prices.get(f"NSE:{symbol}") or {}
            price = float(snapshot.get("last_price") or snapshot.get("ltp") or 0)
            if price > 0:
                symbol_prices[symbol] = price
        missing = sorted({str(call["symbol"]) for call in calls} - set(symbol_prices))
        if missing and self.core._broker_configured():
            try:
                groww = self.core.get_groww()
                for start in range(0, len(missing), 50):
                    batch = missing[start:start + 50]
                    prices = await asyncio.to_thread(get_ltp_batch_sync, groww, batch, "NSE")
                    symbol_prices.update(prices)
            except Exception:
                pass
        resolved: list[dict[str, Any]] = []
        now = self._now()
        for call in calls:
            price = float(symbol_prices.get(str(call["symbol"])) or 0)
            if price <= 0 and now < datetime.fromisoformat(str(call["evaluation_deadline"])):
                continue
            fallback_price = price if price > 0 else float(call["predicted_buy_price"])
            item = self.observe_price(str(call["id"]), fallback_price, observed_at=now)
            if item:
                resolved.append(item)
        return resolved

    async def run_loop(self) -> None:
        while True:
            try:
                resolved = await self.resolve_once()
                summary = self.summary()
                signature = f"{summary['total_calls']}:{summary['correct_calls']}:{summary['wrong_calls']}:{summary['open_calls']}"
                if resolved or signature != self._last_broadcast_signature:
                    self._last_broadcast_signature = signature
                    await self.core.broadcast({
                        "type": "calls_results_update",
                        "resolved": resolved,
                        "summary": summary,
                        "ts": self._iso(self._now()),
                    })
            except Exception:
                pass
            await asyncio.sleep(RESOLUTION_INTERVAL_SECONDS)
