# Dhruva Multyfi Bridge APK

Private Android notification bridge for Multyfi recommendations.

## Locked rules

- Reads only `Stock Name` and `Entry Range`.
- Sends a `GTT_BUY` intent for NSE cash / CNC delivery.
- Quantity is always `100`.
- Trigger reference is the upper entry price.
- Maximum permitted buy price is upper entry + `1.00%`.
- Target, stop-loss and sell automation are omitted.
- Duplicate same-day recommendations with the same symbol and entry range are blocked.
- Groww credentials are never stored in the APK.

## Gateway payload

The configured endpoint receives an authenticated JSON POST containing `symbol`, `entry_low`, `entry_high`, `trigger_price`, `max_buy_price`, `quantity: 100`, `order_type: GTT_BUY`, `product: CNC`, and `price_buffer_percent: 1.0`.

The Dhruva gateway must validate the NSE instrument and funds, normalize to the instrument tick size, and translate the intent into Groww's current GTT API schema from the gateway's whitelisted static IP.

## Setup

1. Install the APK.
2. Grant Notification Access.
3. Enter the Dhruva gateway endpoint and bridge token.
4. Optionally set Multyfi's exact Android package name.
5. Run the local SGFIN parser test.
6. Test gateway reachability.
7. Turn on Live automatic GTT buying after the gateway is ready.

HTTP is permitted for LAN testing; use HTTPS in production.
