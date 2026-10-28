# Evaluation program: what Unbidden lacks to work across many different projects

Started 2026-10-28. The goal is to find out where the product fails on real, varied repositories and why, fix the
general causes, and show with paired comparisons that each fix helps on repositories it was not developed on. The
person improving Unbidden is the engineer (Claude Code), from the evidence; Unbidden does not modify itself.

## Corpus

`bench/repos/corpus-2026-10-28.yaml`, 100 repositories, produced by `bench/corpus.py`:

- **Pool.** One GitHub search per stratum on 2026-10-28, 100 candidates each, saved to
  `bench/corpus/2026-10-28-pool.json` with its queries. Search ranking changes over time, so reproducibility rests on
  this committed pool, not on GitHub.
- **Strata.** Language x popularity: 50–499, 500–4,999 and ≥5,000 stars; pushed in the last six months.
- **Allocation.** Python 30, TypeScript 18, JavaScript 12, Go 10, Rust 7, Java 7, Ruby 5, PHP 5, C# 3, Kotlin 3. It is
  weighted toward what Unbidden analyzes, but languages it does not analyze stay in the denominator: the corpus
  measures reach as well as depth.
- **Exclusion rules,** fixed before the draw and counted per stratum in the corpus file: not an OSI license, fork,
  archived, over 500 MB, a list/course/collection by name or description, or used while developing Unbidden.
- **Draw.** Within each stratum, eligible candidates are shuffled with seed `20261028` and the quota is taken.
- **Splits.** Within each language, a second seeded shuffle assigns dev / validation / holdout by largest remainder
  (40 / 32 / 28), so every language is in every split.
- **Commits** are pinned to the default branch's HEAD on the same day.
- **Kept as drawn.** A few repositories are not conventional software (an internship list, a hosts file, an archive
  of trending pages). The rules let them through, and they stay: knowing when there is nothing to do is part of
  working reliably. Removing them after seeing the draw would be selection by outcome.

## Splits and how they are used

| Split | Size | Use |
|---|---|---|
| dev | 40 | Run in batches; failures analyzed; general fixes developed against them. Re-run after fixes (regression) |
| validation | 32 | Run only with a frozen version, to check that dev fixes generalize. Never debugged directly: what it shows becomes a hypothesis tested on dev |
| holdout | 28 | Run once, at the end, with the final frozen version and protocol |

## Tiers, by cost

| Tier | What runs | Remote API | Local model | When |
|---|---|---|---|---|
| **S, static** | checkout, `init`, `map --no-model`, `scan` (the repository's own tools in the sandbox), `decide` (with the CI's verdicts) | none | none | now, every split |
| **P, probes** | S plus one robustness probe per Python package | Muse Spark, about US$0.015 per repository | no (fallback denied) | after a verified balance |
| **F, full cycle** | `watch --once`: probes, experiments, CI parity, proposals to forks | Muse Spark, capped per repository | no | after a verified balance |

Tier S costs package downloads, Docker CPU and disk only. Images a run creates are removed after it
(`--cleanup-images`); nothing else on the machine is touched. No paid tier starts without a balance verified on the
dashboard (`unbidden spend --verified-balance`).

## What is recorded per repository

Everything comes from Unbidden's own state, never from its printed output (`bench/scale.py:read_state`): checkout,
stack and blind spots, dependency provisioning, every analyzer with completeness, findings and error, the CI's commands,
Python versions and verdict, opportunities with the Director's decision and reason, probes (decided and ran),
experiments with provenance, verdicts, proposals, model runs, spend, time and memory. Then one **root cause**
(`bench/causes.py`).

## Root causes

Each repository gets the first cause, in this order, that explains where it stopped. "Nothing to do" is a result, not
a failure, but it is told apart from "could not look".

| Cause | Meaning |
|---|---|
| `checkout_failed` | could not fetch the pinned commit |
| `not_software` | no source files of any language Unbidden or the corpus knows |
| `unsupported_language` | only languages Unbidden does not analyze (named as blind spots) |
| `no_dependency_manifest` | a supported language without a manifest Unbidden can install from |
| `deps_python_version`, `deps_private_or_network`, `deps_project_metadata`, `deps_native_build`, `deps_resolution`, `deps_other` | the dependency image failed, by the installer's own message (metadata: the project's own version or readme could not be built, nothing compiled) |
| `no_applicable_analyzer` | installed, but none of Unbidden's tools applies (`xo`, a custom linter) |
| `analyzer_failed` | tools applied and none completed |
| `findings_declined` | findings exist and the Director declined all of them, with reasons (environment, scope, style) |
| `nothing_found` | analyzers complete, no finding |
| `actionable` | at least one opportunity the Director would act on |
| `unclassified` | none of the above: read by a person and either given a cause or used to add one |

## Metrics

Reported per split and per version, with Wilson 95 % intervals and the eligible denominator stated:

- reach: stack supported, dependencies installed, an analyzer complete, CI understood (all over all repositories;
  CI understood is a measure beside the cause, not a cause: a repository can be analyzed without it);
- depth: findings, opportunities, the Director's act / decline / wait, decline reasons (over bootstrapped);
- root-cause distribution;
- cost: seconds, memory, image disk, remote US$ (tier S: 0);
- for tiers P and F: probes run, crashes, experiments, verdicts, L4 (with CI parity), false L4s found by audit.

## Comparing versions

The same repositories, the same pinned commits and the same tier, run under two Unbidden trees. Per binary outcome
(bootstrapped, analyzer complete, CI understood), the paired difference is tested with an exact McNemar test on
discordant pairs. Every repository that changed is listed with both causes, regressions first. A fix is kept when
it moves the dev batch it targets, regresses nothing in the dev regression set, and moves validation in the same
direction once frozen. A fix that only helps the repositories it was written for is a per-repository patch and is
not accepted.

## Phases

1. **Dev batch 1.** 15 dev repositories, tier S, the version at program start (baseline).
2. **Analysis.** Root causes, grouped; the most frequent general causes become fixes, each with a unit test.
3. **Regression.** The same batch with the new version, compared paired. Then dev batch 2 (new repositories) with
   the new version.
4. Repeat 2–3 until all 40 dev repositories have run, at least twice.
5. **Validation.** All 32 with a frozen version; compare against the baseline version on the same 32, paired.
6. Tiers P and F on dev, then validation, once a balance is verified.
7. **Holdout.** 28 repositories, once, frozen, as far as the verified budget allows.

Every run's record is committed as produced; notes are added below the record, never into it.
