from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from threading import RLock
from typing import Any, Dict

from .paths import SETTINGS_PATH

_LOCK = RLock()
_DEFAULTS: Dict[str, Any] = {
    "expected_static_ip": "",
    "manual_execution_enabled": True,
    "paper_mode": False,
    # v6.4.1: research discovery is full-breadth. These legacy caps are retained only
    # for settings-file compatibility and are no longer used to truncate the NSE equity universe.
    "universe_size": 0,
    "intraday_scan_size": 0,
    "horizon_scan_size": 0,
    "full_nse_breadth_enabled": True,
    "universe_refresh_interval_seconds": 600,
    "full_breadth_ltp_interval_seconds": 180,
    "full_breadth_daily_research_interval_seconds": 900,
    "daily_history_warm_batch": 64,
    "new_listing_history_warm_batch": 16,
    "weekly_target_pct": 10.0,
    "monthly_target_pct": 50.0,
    "etf_target_pct": 5.0,
    "weekly_min_score": 80.0,
    "monthly_min_score": 84.0,
    "horizon_min_confidence": 0.50,
    "horizon_min_data_confidence": 0.72,
    "weekly_min_observations": 1,
    "monthly_min_observations": 1,
    "weekly_observation_bucket_minutes": 30,  # telemetry only; not a publication pseudo-replication gate
    "monthly_observation_bucket_minutes": 60,  # telemetry only; not a publication pseudo-replication gate
    # v6.5.0 strategic recovery controls
    "strategic_recovery_enabled": True,
    "strategy_promotion_requires_validation": True,
    "near_miss_telemetry_enabled": True,
    "recovery_max_candidate_passes": 6,
    "market_hours_priority_live_scans": True,
    "strategy_champions_per_horizon": 24,
    "strategy_discovery_enabled": True,
    "strategy_discovery_weekday": 5,
    "strategy_discovery_hour": 10,
    "fundamentals_ttl_hours": 24,
    "daily_history_ttl_hours": 12,
    "intraday_history_ttl_minutes": 5,
    # v6.2.4: independent workers + bounded cached intraday scanning.
    "intraday_history_warm_batch": 40,
    "history_intraday_target_days": 5,
    "intraday_worker_interval_seconds": 120,
    "intraday_bootstrap_batch": 100,
    "market_snapshot_interval_seconds": 30,
    "global_context_interval_seconds": 300,
    "sector_context_interval_seconds": 300,
    "fundamentals_worker_interval_seconds": 60,
    "fundamentals_refresh_batch": 12,
    # v6.8.0 shared evidence producers. Scanner cadences remain unchanged.
    "news_worker_interval_seconds": 120,
    "event_worker_interval_seconds": 300,
    "institutional_worker_interval_seconds": 300,
    "algorithm_worker_interval_seconds": 300,
    "horizon_worker_interval_seconds": 300,
    "horizon_recovery_batch_size": 120,
    "broker_probe_interval_seconds": 300,
    "live_update_interval_seconds": 60,
    "maintenance_worker_interval_seconds": 90,
    "etf_worker_interval_seconds": 600,
    "circuit_worker_interval_seconds": 120,
    "circuit_nextday_worker_interval_seconds": 60,
    "international_worker_interval_seconds": 120,
    "global_india_worker_interval_seconds": 300,
    "strategy_worker_interval_seconds": 600,
    "circuit_scan_size": 40,
    "circuit_live_max_per_side": 3,
    "circuit_nextday_max_longs": 5,
    "circuit_nextday_min_score": 84.0,
    "international_max_longs": 5,
    # v6.3.1: U.S. research is a frozen weekly LONG-only book to reduce turnover.
    "international_weekly_max_longs": 5,
    "international_weekly_freeze_et": "09:45",
    "international_weekly_latest_entry_et": "11:00",
    "international_weekly_min_score": 78.0,
    "international_weekly_cost_reserve_pct": 0.50,
    "international_weekly_target_cap_pct": 8.0,
    "international_new_call_cutoff_et": "15:00",
    "global_india_max_per_side": 5,
    # v6.2.1 reliability: central Groww historical-data pacing and adaptive backoff.
    # These defaults are deliberately conservative; the system slows itself further after HTTP 429.
    "history_min_request_interval_seconds": 1.25,
    "history_429_backoff_base_seconds": 5.0,
    "history_429_backoff_max_seconds": 60.0,
    "history_429_max_retries": 3,
    "history_invalid_symbol_quarantine_hours": 12.0,
    # v6.2.3: Groww /v1/historical/candles enforces per-request window limits.
    # Daily history is fetched in <=175-day chunks (below the documented 180-day maximum)
    # and merged locally. Two chunks provide enough bars for SMA200 without oversized requests.
    "history_daily_chunk_days": 175,
    "history_daily_target_days": 350,
    "history_daily_min_rows": 220,
    "history_bootstrap_startup_batch": 20,
    "history_bootstrap_cycle_batch": 8,
    "etf_history_warm_batch": 6,
    "international_enabled": True,
    "news_enabled": True,
    "max_open_manual_orders": 8,
    # v6.7.0 execution-integrity and evidence-governance controls.
    "execution_slippage_reserve_bps": 10.0,
    "execution_min_net_edge_rupees": 0.0,
    "execution_integrity_worker_interval_seconds": 120,
    "backup_worker_interval_seconds": 3600,
    "cohort_min_samples_for_live_use": 50,
    "cohort_max_wilson_width_for_live_use": 0.30,
}


def _atomic_write(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        try:
            if os.path.exists(tmp):
                os.unlink(tmp)
        except Exception:
            pass


def migrate_morning_freeze_settings(path: Path = SETTINGS_PATH) -> Dict[str, Any]:
    """Upgrade persisted horizon settings to the morning-freeze contract.

    v6.3.2 changed the defaults, but an in-place upgrade preserves data/settings.json.
    Older installs can therefore retain weekly/monthly observation gates of 6/4 even
    though repeated same-morning scans are no longer independent evidence. This
    migration changes only those two keys and preserves every other persisted key.
    """
    with _LOCK:
        raw: Dict[str, Any] = {}
        if path.exists():
            try:
                loaded = json.loads(path.read_text())
                if isinstance(loaded, dict):
                    raw = dict(loaded)
            except Exception:
                # Invalid settings already fall back to defaults in load_settings().
                # Do not overwrite an unreadable file during an upgrade.
                return {
                    "changed": False,
                    "reason": "INVALID_SETTINGS_JSON",
                    "weekly_before": None,
                    "monthly_before": None,
                    "weekly_after": _DEFAULTS["weekly_min_observations"],
                    "monthly_after": _DEFAULTS["monthly_min_observations"],
                }
        weekly_before = raw.get("weekly_min_observations")
        monthly_before = raw.get("monthly_min_observations")
        raw["weekly_min_observations"] = 1
        raw["monthly_min_observations"] = 1
        # v6.4.1: legacy scan-size settings are no longer research-universe caps.
        breadth_before=(raw.get("universe_size"),raw.get("intraday_scan_size"),raw.get("horizon_scan_size"))
        full_breadth_before=raw.get("full_nse_breadth_enabled")
        raw["universe_size"] = 0
        raw["intraday_scan_size"] = 0
        raw["horizon_scan_size"] = 0
        raw["full_nse_breadth_enabled"] = True
        changed = weekly_before != 1 or monthly_before != 1 or breadth_before!=(0,0,0) or full_breadth_before is not True
        if changed or not path.exists():
            _atomic_write(path, raw)
        return {
            "changed": changed,
            "reason": "V633_MORNING_FREEZE_SETTINGS",
            "weekly_before": weekly_before,
            "monthly_before": monthly_before,
            "weekly_after": 1,
            "monthly_after": 1,
        }


def load_settings() -> Dict[str, Any]:
    with _LOCK:
        data = dict(_DEFAULTS)
        if SETTINGS_PATH.exists():
            try:
                raw = json.loads(SETTINGS_PATH.read_text())
                if isinstance(raw, dict):
                    # v6.3.7 safety net: the Morning Freeze contract no longer treats
                    # repeated same-morning scans as independent evidence. Older in-place
                    # installs can preserve 6/4 here, so normalize the runtime file itself.
                    # Preserve unknown/future keys by rewriting the original raw mapping.
                    healed = False
                    for gate in ("weekly_min_observations", "monthly_min_observations"):
                        if gate in raw and raw.get(gate) != 1:
                            raw[gate] = 1
                            healed = True
                    for cap in ("universe_size","intraday_scan_size","horizon_scan_size"):
                        if raw.get(cap) != 0:
                            raw[cap] = 0
                            healed = True
                    if raw.get("full_nse_breadth_enabled") is not True:
                        raw["full_nse_breadth_enabled"] = True
                        healed = True
                    if healed:
                        _atomic_write(SETTINGS_PATH, raw)
                    for k in _DEFAULTS:
                        if k in raw:
                            data[k] = raw[k]
            except Exception:
                pass
        # These are policy invariants in Morning Freeze, not user-tunable pseudo-replication gates.
        data["weekly_min_observations"] = 1
        data["monthly_min_observations"] = 1
        data["universe_size"] = 0
        data["intraday_scan_size"] = 0
        data["horizon_scan_size"] = 0
        data["full_nse_breadth_enabled"] = True
        return data


def update_settings(patch: Dict[str, Any]) -> Dict[str, Any]:
    allowed = set(_DEFAULTS)
    clean = {k: v for k, v in patch.items() if k in allowed}
    if "expected_static_ip" in clean:
        clean["expected_static_ip"] = str(clean["expected_static_ip"] or "").strip()
    # Morning Freeze policy invariant: repeated same-morning scans are telemetry, not independent evidence.
    for gate in ("weekly_min_observations", "monthly_min_observations"):
        if gate in clean:
            clean[gate] = 1
    for cap in ("universe_size","intraday_scan_size","horizon_scan_size"):
        if cap in clean: clean[cap]=0
    if "full_nse_breadth_enabled" in clean: clean["full_nse_breadth_enabled"]=True
    with _LOCK:
        current = load_settings()
        current.update(clean)
        _atomic_write(SETTINGS_PATH, current)
        return current
