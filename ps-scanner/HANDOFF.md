# PS Scanner handoff

Current source version: **6.5.1**.

The canonical source is this `ps-scanner/` directory. Runtime state is intentionally not committed. On a Mac installation, runtime state remains under `~/Applications/PS_Scanner_Final/data`, logs under `~/Applications/PS_Scanner_Final/logs`, and local credentials under the secure runtime data path.

The v6.5.1 hotfix was produced after diagnostics showed four issues: Weekly/Monthly symbol collision, ETF missed-freeze recovery blocked by the morning-window rule, an International recovery fetch that could remain running too long, and SQLite disk-I/O failures propagating across workers. The source here includes the corresponding code fixes and the v6.5.1 regression test.

Do not weaken hard risk, freshness, data-quality, or order-safety gates to force recommendation counts. Strategy combinations remain subject to validation/learning rules rather than being treated as automatically reliable.
