# Regression v7 at product ac88071: Prefect B-r13 and A-r13

Frozen worktree `~/unbidden-ai-s10-ac88071`, `s10-dev`. B-r13 1976 s, US$0.2229; A-r13 2000 s, US$0.2254. Both
completed. No interventions, no branch.

- Checks reproduced: 1033 collected in the CI's group 1 of 18, 11 failed. The sweep fix (25152f0) held: about 5 s per
  experiment instead of 38 s; all four cycles finished.
- B and A: 229 type-check opportunities `not measured` ("cannot judge: incomplete reports from ruff, pyright"); 281
  ruff-style opportunities declined (the team's CI does not run ruff). Reproduced on Prefect: pyright ran out of
  Node's default heap in the Python image, and ruff's (16784) and pyright's (11642) reports were cut at the scan's
  2000-finding cap; ruff, not run by the CI, gated mypy's fixes. Fixed in b603744; all three reports then complete.
- A: the goal waited on an API integration. Attempt 1 read every POST listing (D-061 holds: flows 50, flow runs 10000,
  task runs 30000, deployments 0, each complete by its count) and was rejected with no failed operation named: the
  oracle's cross-check required the same completeness label from a second read with another page size, which had no
  count to confirm it (same records, 0 differ). Fixed in the next commit. Attempt 2: the model chose no documented
  read operation; the need was abandoned and the goal blocked ("no integration could be validated").
- Open: a rejection whose failures list is empty says nothing about why (here the reason was only in the verdict's
  per-operation `passed`).
