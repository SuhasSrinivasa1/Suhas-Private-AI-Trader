# PS Scanner v6.8.12 Recommendation Recovery

Branch: `release/ps-scanner-v6.8.12-recommendation-recovery`

This branch was opened from main SHA `4fd6b6f30dfbde6f92a441a05f8bf9aa7d5dd84c` to preserve the historical main baseline while recovering the exact v6.8.12 production source supplied from the Mac.

## Production findings

- Intraday full-breadth deep pass could run for roughly 108 minutes.
- Global->India identities could publish before NSE continuous trading and resolve before a legitimate live entry.
- ETF and International shortage funnels were under-instrumented.
- Repeated unsupported Yahoo fundamentals lookups created avoidable producer/log load.
- Support export required a low-disk guard after a disk-full / SQLite I/O cascade was observed.

## Recovery policy

- Do not relax trading or research gates.
- Preserve full NSE breadth; use bounded rotating evaluation rather than a top-N cap.
- Future/pre-open recommendations are PREPARED until a fresh valid-session quote establishes entry.
- Structurally pre-activation outcomes are VOID, regardless of whether they were WIN/LOSS/MISS.
- Preserve the existing v6.8 shared evidence fabric and passive endpoint contracts.
- ETF remains enabled and is repaired rather than removed.

## Source provenance

The sanitized backend recovery source snapshot prepared from the exact uploaded v6.8.12 source has SHA-256:

`209b8815d6a14cfe6123cc457108fe5b8f8af8e1e5348550f47d12e19e9c2331`

The user's source export intentionally omitted the installed `static/` UI directory and installer/runtime directories. Therefore this branch must not be merged to main or represented as a complete installable v6.8.12 release until those exact production files are recovered and CI is run from the reconstructed full tree.

Runtime DBs, credentials, logs, caches, support archives and source backup files are intentionally excluded from source control.
