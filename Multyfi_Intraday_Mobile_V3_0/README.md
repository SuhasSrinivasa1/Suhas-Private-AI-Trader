# Multyfi Intraday Mobile V3.0

Clean Android rewrite focused on professional paper tracking and daily guarded learning.

- Captures eligible Multyfi notifications through Android Notification Listener access.
- Uses the official Groww REST quote API after the user supplies and validates credentials.
- Stores real candidate tick replays; there are no demo/sample trades.
- Symmetric LONG/SHORT paper engine with stops, profit trail, reversal handling and 14:55/15:15 risk locks.
- Replay-based Champion/Challenger learning with chronological validation gates.
- Full daily `.txt` diagnostic export including candidates, paper trades, activity/errors, learning comparisons and raw market ticks. Secrets are excluded.

V3.0 is paper-only and does not place broker orders.
