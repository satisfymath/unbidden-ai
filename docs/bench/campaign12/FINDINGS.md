# Campaign 12: findings as they appear (product defects, harness defects, observations), dated, never edited later

Each line: date · where seen · what · class (defect / wording / harness / limit) · status (open / fixed in <sha> /
accepted limit). Fixes happen only in phase 6; until then the line stays open and the record keeps the behaviour.

- 2026-11-01 · Rich product walk · the Director reported "3 pull requests already open (cap 3)" with one pull request
  on the fork: local proposals counted as open pull requests · defect (decisions) · fixed before the freeze in
  `2f7eee5` (candidate).
- 2026-11-01 · Level A pilot · `scan` does not run the project's checks (analyzers only); they run in the agent's first
  cycle. A person reading "scan: run the repository's own checks in the sandbox" (the command's help) expects them
  there · wording/UX · open.
- 2026-11-01 · Level A pilot, humanize · the dependency image lacks `msgfmt` (gettext): the CI's
  `scripts/generate-translation-binaries.sh` fails with exit 127, recorded as `infra_failed` (correct class). The image
  does not read system packages a CI job installs with apt · limit (environment reproduction) · open.
- 2026-11-01 · Level B pilot, rich · the lab logs "asking the local model for a candidate" while the mandate denies
  local inference and the call goes to Meta's API (`measuring the frontier candidate` follows) · wording · open.
- 2026-11-01 · Level A pilot · dependency images of development repositories were cached from earlier stages, so
  "environment reproduced" took 10-20 s; a fresh machine builds them (minutes). Recorded per run (`image_age`) ·
  harness/observation · recorded.
- 2026-11-01 · Level A pilot · the ledger's `spend_calls` shown by the dashboard for a workspace named like an earlier
  one (`humanize`) counted that earlier spend; the campaign names workspaces `c12-<name>` to keep rows apart ·
  limit (workspace = repository name) · known, documented in RELEASE.
