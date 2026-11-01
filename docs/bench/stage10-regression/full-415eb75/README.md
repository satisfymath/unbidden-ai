# Stage 10 regressions, part 3: codex-lb full cycles at product 415eb75 (the merge-migration fix), development

Worktree `~/unbidden-ai-s10-415eb75`, `s10-dev` 8.09 -> 8.60 (US$0.51); B-1 440 s, A-1 534 s; the lab's data as in
the evaluation. The harness archived both workspaces onto the earlier regression's archives of the same names
(nested `.unbidden/`; moved to `codex_lb-reg-B-1-415eb75` and `-A-1-415eb75`; fixed in 8f6536c).

- Checks reproduced (6422 collected, 34 failed as before).
- The migration graph now has one head (bbb0f83 held): the experiment on `proxy_pool_members.endpoint_id` reached
  the candidate step. The rule-written index was not attempted (the column's `mapped_column(` spans four lines; the
  rule handled one line), the model was asked twice and each change added the project's own lint findings (7, then
  1 in B / 3 in A): **not measured**, "no candidate change keeps the project's own checks clean". Fixed in 60da8ac
  (the rule edits multi-line declarations in the project's layout); offline on this commit the rule's candidate adds
  0 findings. Repeated next.
- Consistency: 10 questions; 8 blocked on `GET /api/request-logs` read incomplete at its 100,000-record bound (a
  partial read, correctly not concluded); 2 blocked on bearer-only endpoints (`/v1/usage`, `/api/fleet/observability`)
  with the dashboard's auth disabled — now probed once anonymously before blocking (next commit).
- A: the goal waited on the integration (not validated: the same bound), then blocked.
- No false conclusion; no action.
