# Stage 10 regressions, part 1: preparation and the projects' checks only (no model, no spend)

After the frozen evaluation was closed (`../../stage10-eval/README.md`), each correction was tested in a unit test that
fails on the version before it, then run for real with `bench/checks_only.py` (stack, dependency image under a lab
mandate, the CI's test plan, one round offline in the sandbox) from a worktree frozen at that commit, on the same
pinned commits and lab clones as the evaluation. Every attempt is kept (`r<N>-<sha>/<app>-checks.json`).

| Run | Product | App | Status (tests collected) | What it showed, and the correction that followed |
|---|---|---|---|---|
| r1 | d9b9335 | codex-lb | infra_failed | branch chosen right (f60bfb4); the sandbox has no `make` -> c4cc783 (make targets run as their recipes) |
| r2 | c4cc783 | codex-lb | infra_failed | `PYTHONFAULTHANDLER=1 uv run pytest` kept `uv run`, which built the project offline -> 6f48b39 |
| r3 | 6f48b39 | codex-lb | failed (6422) | **reproduced**; 34 failures, git/release-script tests (no `.git` in the snapshot): pre-existing, both sides |
| r4 | d582d15 | aegra | infra_failed | interpreter resolved at provisioning (d582d15); `ModuleNotFoundError aegra_api` (member's src/) -> 52e2d8c |
| r5 | 52e2d8c | aegra | infra_failed | `PackageNotFoundError aegra-api` (member metadata) -> d173adc |
| r6 | d173adc | aegra | failed (2429) | **reproduced**; 21 failures marked "needs network" |
| r7 | 0c1df68 | rag-api | infra_failed | test requirements installed, container-runtime step left out (0c1df68); `OPENAI_API_KEY` missing -> 15b694f |
| r8 | 15b694f | rag-api | infra_failed | 194 passed, 1 failed, but the CI's `--junitxml` overrode the lab's report -> cbf1ecf |
| r9 | cbf1ecf | all three | failed (6422 / 2429 / 195) | **all three reproduced on one commit** |

rag-api's 195: its CI's `--maxfail=1` stops at the first failure, a test that downloads NLTK data (the sandbox is
offline); 219 non-integration tests exist. Its integration tests (testcontainers, a pgvector container) are left out
and said: the sandbox has no container runtime and the host's Docker socket is never given to a project's code.

## The corrections (each with a unit test that fails before it)

1. **CI step conditions** (f60bfb4): what a step only prints is not a call (codex-lb's skip echo says "pytest");
   steps under a condition unknown outside GitHub and its negation are two branches, the one that runs tests is taken
   and the unknown said; a plan's own steps must run tests; a pytest run that exits 0 with no report is
   `not_collected` ("no test ran"), never "passed".
2. **make** (c4cc783, 6f48b39): targets run as their recipes, prerequisites first, a shell a line, `$(VAR)` and the
   call's overrides; a JavaScript build in a Python job left out and said; runner prefixes removed after assignments.
3. **Interpreter** (d582d15): the CI's `uv python install|pin` is evidence for the interpreter chosen at provisioning;
   the line leaves the offline run; the plan says whether the image satisfies it. Downloads stay off. Base and
   candidate run on the same image (one image per commit, recorded in each experiment's provenance).
4. **Workspaces** (52e2d8c, d173adc): a member's `src/` is on the path; each member's metadata is in the image.
5. **Test requirements and container runtimes** (0c1df68): files the job installs with `pip install -r` are installed
   into the image (each as its own install, as the job does); tests whose files import a container runtime library are
   found with their markers, and a step that selects them is left out with why; no repository is named.
6. **Environment and reports** (15b694f, cbf1ecf): the job's environment always reaches the run; the CI's own
   `--junitxml` is removed so the lab's report is written.

## Independent reproduction (the harness's author, isolated containers, network for installs, no Docker socket)

What each project's CI requires, and how it compares with Unbidden's runs (this does not change the evaluation):

| App | As its CI runs it | Outcome | Compared with Unbidden |
|---|---|---|---|
| codex-lb | `make test-unit` (bun 1.3.14 builds the frontend, `uv sync --dev --frozen`, Python 3.13) | 6349 passed, 2 failed, 71 skipped (6422) | same 6422 collected; Unbidden leaves the frontend build out (said) and runs without `.git` (34 more failures, both sides) |
| aegra | `uv python install 3.12`, `uv sync --all-packages`, `pytest libs/aegra-api/tests/{unit,integration}` | 2422 passed, 7 skipped (2429) | same 2429; 21 "needs network" failures in the offline sandbox |
| rag-api | `pip install -r requirements.txt`, then `-r test_requirements.txt` (one install fails to resolve), `OPENAI_API_KEY=test_key pytest --maxfail=1` | 221 passed, 6 skipped (227); integration: 3 errors without a container runtime | 195 collected offline (stops at an NLTK download); integration left out, as needed |
