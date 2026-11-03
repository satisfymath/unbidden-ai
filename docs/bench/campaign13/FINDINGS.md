# Campaign 13 findings

Dated lines, newest last. Each says what was seen, where (record or log), and what follows.

- 2026-11-03 · plan · Campaign 13 opened on `main` 0.12.8 (`0cab77d`); campaign 12's fixes (`feat/64-campaign`,
  `726009d`) are ported by WS0, not merged. Criteria `docs/ROAD-TO-1.0.md`; protocol here; decision D-065.
- 2026-11-03 · WS0 · Campaign 12's product commits ported to `main` 0.12.8 on `feat/67-port-campaign12` (four
  commits replayed, conflicts in `lab/perf.py`, `daemon/cycle.py`, `tests/unit/test_cycle.py` resolved with main's
  asks and `say()`). Main's spend question amended the machine ledger while the router checks the mandate's cap; it
  now raises the mandate's cap and releases the held blocks. 1361 tests passed, pyright clean. No model spend. Not
  pushed: another session releases on main; the PR waits for David.
