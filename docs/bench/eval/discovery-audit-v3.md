# Capability B, audited: are the opportunities v3 would act on true?

Three capabilities are measured apart, because more of one is not more of another:

- **A. Enter and analyze** a repository: reach (`PROGRESS.md`). Coverage.
- **B. Discover a true opportunity**: of what the Director keeps to act on, how much is a real defect worth fixing.
  Measured here, by reading the code of every finding.
- **C. Demonstrate a useful improvement**: a candidate measured in the lab against the team's checks (L4) and, where a
  deployment exists, live (L5). Not measured in the static tier.

## Method

Every repository where v3 (static tier, dev and validation) would run an experiment: each finding read at its line,
and labelled real-with-impact, real-but-trivial (dead or redundant code, no behavior), environment (the finding comes
from Unbidden's environment, not the code) or false positive (the rule misreads a correct pattern). Labelling is not
debugging: no rule was changed from validation's findings; the general causes below go to dev as hypotheses.

## Result

| Repository (split) | Findings kept | Real, with impact | Real, trivial | Environment / false positive |
|---|---|---|---|---|
| taskuary (dev) | 16 | **2** | 10 | 4 (pytest fixture parameters) |
| Radarr (dev) | 93 | 0 | 0 | 93 (type errors inside `../deps/node_modules/@types/node`) |
| astrbot_plugin_livingmemory (val) | 50 | 0 | 0 | 50 (pytest fixture parameters) |
| enhanced-FaaS-in-China (val) | 2 | 0 | 2 (mutable defaults) | 0 |
| chronoframe (val) | 8 | 0 | 0 | 8 (Nuxt's generated `.nuxt/tsconfig.*.json` missing) |
| doubtfire-web (val) | 58 | 0 | 0 | 58 (a test runner's globals in `.spec.ts`: `describe`, `vi`, `expect`) |
| cloudflare/agents (val) | ~900 | 0 | 0 | ~900 (workspace packages not built; JSX in examples) |

**1 of 7 repositories (14 %) holds an opportunity worth acting on.** The two real defects, in taskuary:
- `taskuary/server.py`: `_run_kind` imports `assistant` locally at line 1510, which makes the name local to the whole
  function; line 1250 (`if kind == 'idea.act': return assistant.act(...)`) raises `UnboundLocalError` for every
  `idea.act` operation. A latent crash in a request handler (ruff F823).
- `tests/test_histgen.py`: the class `VocabularyFromHistoryTests` is defined twice; the second replaces the first, so
  three tests never run (ruff F811).

## What it says about Unbidden

Reach grew; discovery did not keep up. Most of what survives the Director's CI rules in the static tier is still
Unbidden's environment, from causes that repeat and are general:
1. findings located outside the repository (dependencies' own type errors);
2. F811 on a function parameter: pytest's fixture injection, not a redefinition (a duplicated class is still one);
3. generated code a tool expects (Nuxt's `.nuxt`, like Prisma's client, already handled);
4. a test runner's globals in test files;
5. workspace packages that must be built before their dependents type-check.

1 and 2 are fixed next, tested on dev; 3 to 5 are hypotheses. Capability C needs the lab, which needs a model for
anything but a tool's own fix, and no credit is spent before a balance is verified.
