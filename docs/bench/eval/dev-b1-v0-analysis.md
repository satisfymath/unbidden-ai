# Dev batch 1, baseline (v0, `unbidden/` tree 3090aaf): root causes

The first 15 dev repositories of `corpus-2026-10-28.yaml`, static tier (no model; US$0). Record: `dev-b1-v0.json`.

| Root cause | n | Repositories | What it was, by the installer's or Unbidden's own message |
|---|---|---|---|
| actionable | 1 | taskuary | 16 findings of Unbidden's baseline ruff rules (bugs, not style); 5 opportunities to experiment on |
| findings_declined | 3 | tpu-inference, Cirq, vscode-beads | a green CI of the same tool (ruff; pyright, 2,000 findings in 250 groups on Cirq), or a tool the CI does not run |
| nothing_found | 4 | headroom, unfurl, internship list, hosts | analyzers complete, no finding |
| deps (Python) | 4 | IsaacCapture, mistral-common, hermes-webui, inspect_evals | a path source; a pinned uv; a stale uv.lock; uv switched interpreter for a group needing Python 3.12 |
| deps (Node) | 1 | compass-calendar | a bun project taken for one without a lockfile, installed with npm: ERESOLVE |
| no_dependency_manifest | 2 | llm-d, Osmantic/ODS | Python only in subdirectories, each with its own requirements.txt; no manifest at the root |

Also seen, not a root cause on its own:
- mypy configured but not installed in the project's environment (Cirq, headroom): the analyzer is reported failed.
- An ESLint 10 resolved without a lockfile could not read a legacy `.eslintrc` (hermes-webui).
- The classifier had no rule for four of the dependency messages; they were `deps_other` until rules were added.
- The CI was understood in 15 of 15.

Fixed in general before v1 (commit 9bef1e6): every dependency cause above except a git-hosted dependency
(inspect_evals' next layer; needs network the mandate does not grant) and IsaacCapture (its local package depends
on the project itself). Not yet addressed: manifests only in subdirectories, mypy not installed, legacy ESLint config.
