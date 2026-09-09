# Multyfi Intraday Mobile V3.0.1

Clean Android rewrite focused on professional paper tracking and daily guarded learning.

- Captures eligible Multyfi notifications through Android Notification Listener access.
- Uses the official Groww REST API after the user supplies and validates credentials.
- Supports Groww API Key + API Secret approval/checksum authentication.
- Supports Groww TOTP Token + TOTP Secret authentication and generates the current 6-digit TOTP internally.
- Keeps an existing daily Access Token as an optional fallback.
- Stores real candidate tick replays; there are no demo/sample trades.
- Symmetric LONG/SHORT paper engine with stops, profit trail, reversal handling and 14:55/15:15 risk locks.
- Replay-based Champion/Challenger learning with chronological validation gates.
- Full daily `.txt` diagnostic export including candidates, paper trades, activity/errors, learning comparisons and raw market ticks. Secrets are excluded.

## Groww authentication

For **API Key + API Secret**, enter the two values in Settings and tap **Connect • Key + Secret**. Groww's approval-based flow may still require the day's approval on the Groww Cloud API Keys page.

For **TOTP Token + TOTP Secret**, enter the token as the first credential and the secret (or the secret behind the QR code) as the second credential, then tap **Connect • TOTP**. You do not type the rotating six-digit code; V3.0.1 generates it internally.

Credentials are stored using Android Keystore-backed encryption and are excluded from diagnostics.

V3.0.1 is paper-only and does not place broker orders.
