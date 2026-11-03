# Campaign 13 protocol: to 1.0

Criteria: `docs/ROAD-TO-1.0.md` §3. Decision: D-065. Product plan: the work streams in §3 below. Every dated change to
this protocol is appended at the end with its reason; nothing is rewritten after the freeze.

## 1. Rules carried over from campaign 12

Nothing is sent upstream (no pull request, push, issue or comment on a third party's repository). Public copies only
as `satisfymath/c13-<name>` (or the `c12-<name>` copies reset to their pin), each keeping licence, attribution,
provenance, the pinned upstream commit and one documented campaign commit; no secrets, `.env`, personal data or other
projects' configuration copied; no package published and nothing deployed outside the lab by a copy's workflows; the
Meta key never stored as a GitHub secret. Tokens travel by reference (the broker, stdin), never in prompts, commands,
logs, records or URLs. Other sessions' checkouts and labs, and Hosli's containers, are never touched. No transfer
between envelopes; the cap is never amended without David. Failures, blocks and retries are kept. No forced pull
request. Seeded scenarios are reported apart. Development results are calibration, not evidence.

## 2. Envelopes

Authorized once by David with:

```
unbidden spend --envelopes s13-dev=15,s13-pass=15,s13-final=20,s13-confirm=5,<existing envelopes unchanged> \
  --envelopes-total <current total + 55> --source "David, 2026-11-03: campaign 13 to 1.0 within the cap"
```

| Envelope | US$ | Spends on |
|---|---|---|
| `s13-dev` | 15 | bounded real runs per work stream on development repositories |
| `s13-pass` | 15 | the intermediate pass (§6, phase 5) |
| `s13-final` | 20 | the final pass, two runs per Level B repository |
| `s13-confirm` | 5 | repetitions from a clean state |

Each run carries `UNBIDDEN_ENVELOPE` and `UNBIDDEN_RUN=c13-<phase>-<level><n>-<repo>`.

## 3. Product work, in order (each on its own branch from `main`, released per main's convention)

WS0 port campaign 12's fixes · WS1 blocks: retry, ask or declare · WS2 typed value model · WS3 correctness proven by
a test · WS4 production reliability · WS5 security and dependencies · WS6 quality with the team's CI · WS7
environment funnel · WS8 autonomy where a lab can exist. Each ends with `make check`, `make web-check`, a bounded real
run on the development repositories it affects (`s13-dev`), a dated line in `FINDINGS.md`.

## 4. Corpus and labs

The 39 repositories of `bench/campaign12/corpus.yaml` at their pins (copied to `bench/campaign13/corpus.yaml` at the
freeze with the candidate). Labs (compose project `c13-<name>`, synthetic seed, read-only role, health endpoint,
deploy and check steps, a passed drill) on: fst, spoolman (existing); conduit, aegra, ctfd, timetracker, codex-lb
(development); misago, brightbean-studio, gymhero, recruitops-agent, mimirq (independent); netbox (frontier). A lab
that cannot be built is recorded with its cause and the repository stays in Level B in autopilot. Preparation time per
lab is counted as human preparation, apart from the agent's runs.

## 5. Mandate of the final pass ("every permission")

| Field | Value |
|---|---|
| `autonomy.*` | `allow` for observe, run_experiments, provision_dependencies, delegate_synthetic, open_pull_requests, merge_pull_requests, deploy, rollback, use_new_capabilities; act_on_connections `allow` where the lab grants writes |
| mode | `autonomous` on lab repositories (deploy steps + drill); `autopilot` elsewhere, named by the harness as the fallback |
| `models` | option `api`; private code and screenshots to frontier `allow` (public repositories, declared) |
| `egress.package_registries` | pypi.org, files.pythonhosted.org, deb.debian.org, registry.npmjs.org, ghcr.io, registry-1.docker.io, github.com release downloads |
| `egress.github` | the copy, its default branch, max 3 open pull requests |
| `business_constraints.maximum_monthly_spend_usd` | 5 per repository |
| `connections` | read grants on the lab's Postgres and HTTP API; a write grant where the lab declares one |
| deny by design | `destructive_operations`, any production environment, anything outside the copy and the lab |

## 6. Phases and gates

1. Documents (`ROAD-TO-1.0.md`, this protocol, `MEASURES.md`, D-065). Gate: David has read §3 of ROAD-TO-1.0.
2. WS0, WS1, WS2. Gate: unit and web suites green; campaign 12's seven fixed cases green again on main.
3. WS3-WS6. Gate: each class has at least one proven improvement on a development repository, or the stream says why.
4. WS7, WS8, labs built and drilled. Gate: Level A honest counts at least campaign 12's.
5. Intermediate pass (`s13-pass`): Level A on the 39; Level B one run on every lab repository and the eight
   independent Level B repositories of campaign 12. General causes found are fixed (development).
6. Freeze: candidate commit, wheel sha256, harness, corpus, criteria and envelopes in one commit.
7. Final pass (`s13-final`): Level A on the 39 (default mandate, then Debian allowed on the tool cluster); Level B two
   runs on every lab repository (autonomous) and the eight independent repositories (autopilot where no lab); seeded
   scenarios. No product change during the pass; a harness crash is fixed, named, and the affected run repeated.
8. Repetition from clean (`s13-confirm`) of every full chain; independent verification of every pull request; report.

## 7. The agent's questions during autonomous runs

The harness polls `unbidden ask --json` every 30 s and answers by this table only. Each answer is recorded in the run
as an automatic intervention with its rule; a question the table does not cover is answered `later` and recorded as
unanswered. No other help is given to the agent.

| Ask kind | Answer | Condition |
|---|---|---|
| registry | allow | the host is in §5's list; otherwise later |
| credential (model key, connection, GitHub) | the lab or campaign credential, on stdin | it exists in `INVENTORY.md`; otherwise later |
| access, capability | approve | for a lab connection |
| approval (pull request) | approve | autopilot only |
| deploy_steps | adopt | the procedure is the lab's |
| drill | run | lab repository |
| spend | raise to §5's cap | within the envelope |
| merge left to a person | leave | always: the product's own merge rule is what is measured |
| hold | keep | always |
| anything else | later | recorded |

## 8. Independent verification

`bench/campaign13/verify.py` per class: correctness (the new test at base fails, at head passes, in a fresh clone),
security (the scanner at base and head), quality (the team's tools at base and head), latency (the workload replayed
in the lab), reliability (the signal at both deploys). Every verdict "verified", "contradicted" or "no independent
confirmation", with the reason. A human quality reading of every pull request is recorded apart.

## 9. Reporting

`REPORT.md` with the nine dimensions per class of repository and per class of improvement, a failure matrix by cause,
asks raised and answered, retries, cost per class and per run, latency, and each line of ROAD-TO-1.0 §3 marked met or
not with the record that decides it.

## Amendments
