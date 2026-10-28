# Evaluation program: progress

Protocol: `../EVAL-PROGRAM.md`. Corpus: `bench/repos/corpus-2026-10-28.yaml` (100 repositories; dev 40, validation
32, holdout 28). Everything below is the static tier: no model of any kind, US$0 of API.

## Versions

| Version | `unbidden/` tree | What changed, from what the previous run showed |
|---|---|---|
| v0 | 3090aaf | the program's baseline |
| v1 | 166430d | uv projects (interpreter pinned, groups needing another Python, required uv version, stale lockfile, path sources, dependencies read from files), bun and patched dependencies, build errors that keep the installer's explanation |
| v2 | d2e92d2 | CI commands followed through package.json scripts, independent subprojects, yarn classic, Rush and Yarn Berry named |
| v3 | 0c00d9a | an unreadable CI told from one without checks, the Director waits on it, `decide` uses the token, pnpm taken from the lockfile's format |

Every change is general (no rule names a repository) and has a unit test.

## Dev (40), paired

| Outcome | v0 (batch 1, 15) | v3 (same 15) | Gained / lost | Exact McNemar p |
|---|---|---|---|---|
| Bootstrapped (an analyzer complete) | 8 | 13 | 5 / 0 | 0.0625 |
| Dependencies installed | 8 | 11 | 3 / 0 | 0.25 |

All 40 at v3: 20 bootstrapped; 15 in languages Unbidden does not analyze (Go 4, Rust 3, Java 3, Ruby 2, PHP 2,
Kotlin 1); 1 Rush monorepo; 2 with no analyzer that applies (Vue without tsconfig or ESLint; a custom lint script);
2 dependency limits kept on purpose (a dependency from a git repository, which needs network the mandate does not
grant; a local package that depends on its own project).

**Decisions, with the CI readable (v3).** The Director read the team's CI on 36 of 40 (30 green, 6 red, 4 without
checks). It declined more than 2,500 opportunity groups as differences of its own environment (a green CI of the same
tool), and kept two to act on, each with a reason: Unbidden's own bug rules, which that CI does not run (taskuary),
and a red CI (Radarr). At v2 the same repositories had been 1,000+ experiments, because the CI was unreadable and
looked like a commit without checks.

## What the program has found Unbidden lacks

In order of how many repositories it stopped:

1. **Languages:** 15 of 40 dev repositories are in languages Unbidden does not analyze. The single largest gap, and
   architectural (two languages are hard-coded in detection, provisioning, analyzers, tests, CI parity and the lab).
   Deferred by decision until this cycle is closed.
2. **Dependency installation** of real projects (fixed in v1–v3 for the causes seen, by the installers' own messages).
3. **Reading the team's CI**: through package scripts and tox, from forks, and telling "unreadable" from "no checks".
4. **Repository shapes** without a root project: subprojects, Rush, Yarn Berry.
5. **Analyzers that are not the team's**: Vue, custom lint scripts, `xo`, mypy not installed in the project's
   environment.

## Validation (32, frozen v3 against v0)

Never run before v0's baseline run and never debugged. Protocol frozen before the run (`validation-protocol.md`);
record `val-v0.json`, `val-v3.json`, comparison `compare-val-v0-v3.md`.

| Outcome | v0 | v3 | Gained / lost | Exact McNemar p |
|---|---|---|---|---|
| Bootstrapped (an analyzer complete) | 13/32 | 18/32 | 5 / 0 | 0.0625 |
| Dependencies installed | 15/32 | 16/32 | 1 / 0 | 1.0 |
| Stack supported | 18/32 | 18/32 | 0 / 0 | 1.0 |

The same direction and size as on dev (5 gained, 0 lost on 15), on repositories none of the fixes was written from.
With n = 32 the exact test is not below 0.05; pooled with dev batch 1 (10 gained, 0 lost on 47 pairs) it is
p = 0.002, an estimate across two splits, not a pre-registered test.

v3's Director read the CI on 28 of 32 (25 green, 3 red; 4 without checks), declined 208 opportunity groups and left
145 waiting (findings in subprojects the lab cannot reproduce yet, or a CI it could not read), and would act on 5
repositories: Unbidden's own bug rules where the CI does not run them (2), a red CI (2), and chronoframe, whose CI is
green but whose commands, as Unbidden reads them, do not run tsc, so 2 type findings stay open to experiment on. Why
its CI does not show tsc was not investigated: validation is not debugged.

**What validation suggests, as hypotheses for dev** (not fixed from validation):
- uv projects that declare mutually incompatible groups (`[tool.uv] conflicts`) cannot install `--all-groups`
  (anima_lora);
- mypy configured but not installed in the project's environment is now seen in 3 repositories (Cirq, headroom, vllm);
- a second dependency from a git repository (prism-insight): the deliberate limit.

## Cost

US$0 of API for the whole program so far (static tier only). Docker images each run created were removed after it.

## v4: the LanguageAdapter contract and Go (tree 0c0879d), paired against v3

| Split | Bootstrapped v3 → v4 | Gained / lost | Exact McNemar p |
|---|---|---|---|
| Dev (40) | 20 → 25 | 5 / 0 | 0.0625 |
| Validation (32, frozen) | 18 → 21 | 3 / 0 | 0.25 |

Python and Node: no repository changed cause (one decision changed on dev, firekylin, with a readable CI both times).
All gains are Go repositories now analyzed (`go vet` and the compiler, offline). **Coverage, not discovery:** of the 8
Go repositories gained, 7 found nothing and 1 (discobox) had every finding declined; none adds an opportunity worth
acting on. On this evidence, more languages wait until discovery and decision improve (`docs/PLAN.md`).

## v5: Phase 0 and 1 of the plan (PR1–PR9, commit e743e37), paired against v4 on dev

Record `dev-all-v5.json`, comparison `compare-dev-all-v4-v5.md`. Same 40 repositories and commits, same settings
(static tier, 2 workers, 20 minutes), run from a frozen worktree.

| Outcome (dev, 40) | v4 | v5 | Gained / lost |
|---|---|---|---|
| Bootstrapped | 25 | 25 | 0 / 0 |
| Dependencies installed | 25 | 25 | 0 / 0 |
| CI understood | 36 | 36 | 0 / 0 |

Reach unchanged, as expected: these PRs change what evidence counts and what may act, not what can be analyzed.
Four repositories changed decision, all from "findings declined" to "actionable", because the CI equivalence (PR4)
no longer reads a tool's name as a substring. Each was read:

| Repository | What v5 would act on | Why v4 declined it | Verdict |
|---|---|---|---|
| quantumlib/Cirq | Unbidden's pyright, 250 type findings | "pyright" inside "copyright": the CI runs mypy, never pyright | v4's decline was false; whether pyright findings on a mypy-clean project are worth it is the Director's question (PR12 learns it from outcomes) |
| vllm-project/tpu-inference | ruff-baseline B006 (mutable defaults), 5 groups | the CI runs ruff (pre-commit) with the team's rules | by design: Unbidden's own rules are not the team's; real but trivial findings |
| jdillon/vscode-beads | eslint `no-undef` for `module` in `jest.config.js` | the CI runs eslint, on `src` only | the relation is right (the CI does not lint that file); the finding is environment noise (a CommonJS config file) |
| KeepSoftwareSimple/compass-calendar | 152 tsc findings | the CI runs `bunx typescript@7.0.2 -b tsconfig.typecheck.json` | **a gap in PR4**: that step is tsc, at a version and with a config of its own; it should wait, not experiment. Fixed after the run (`85c9d03`), checked on this checkout |

So: one false decline removed (Cirq), one gap found and fixed (compass-calendar), two by design with low-value
findings. Discovery precision did not improve, and was not expected to: that is the Director's work (PR12) and the
discovery causes listed in `discovery-audit-v3.md`. Validation is not re-run for v5: nothing here changes reach, and
the next validation run waits for a candidate worth freezing.
