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
