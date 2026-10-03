from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TransitionDecision:
    action: str
    reasons: tuple[str, ...]


def resolve_direction_transition(
    *,
    desired_action: str,
    ipo_sentinel_long_quantity: int,
    ipo_sentinel_intraday_short_quantity: int,
    external_same_symbol_quantity: int = 0,
) -> TransitionDecision:
    """
    Converts a model direction into an order-safe state transition.

    The engine never reverses directly through zero in one order. If an IPO Sentinel
    delivery long exists and the model turns bearish, the long is exited first. A new
    intraday short can only be considered after a fresh broker reconciliation confirms
    the app-owned long is flat.

    External holdings are never used as inventory for IPO Sentinel exits.
    """
    desired = desired_action.upper().strip()

    if desired in {"PROBE_SHORT", "BUILD_SHORT", "HOLD_SHORT"}:
        if ipo_sentinel_long_quantity > 0:
            return TransitionDecision(
                "EXIT_OWNED_LONG",
                (
                    "BEARISH_REVERSAL_DETECTED",
                    "FLATTEN_IPO_SENTINEL_LONG_FIRST",
                    "REVALIDATE_BEFORE_SHORT",
                ),
            )
        if external_same_symbol_quantity > 0:
            return TransitionDecision(
                desired,
                (
                    "EXTERNAL_SAME_SYMBOL_HOLDING_READ_ONLY",
                    "SHORT_MUST_USE_INTRADAY_PRODUCT_ONLY",
                ),
            )
        return TransitionDecision(desired, ("FLAT_TO_SHORT_ALLOWED_AFTER_RISK_GATE",))

    if desired in {"PROBE_LONG", "BUILD_LONG", "HOLD_LONG"} and ipo_sentinel_intraday_short_quantity < 0:
        return TransitionDecision(
            "COVER_OWNED_SHORT",
            (
                "BULLISH_REVERSAL_DETECTED",
                "COVER_INTRADAY_SHORT_FIRST",
                "REVALIDATE_BEFORE_LONG",
            ),
        )

    return TransitionDecision(desired or "WAIT", ())
