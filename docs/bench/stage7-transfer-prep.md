# Stage 7: human preparation for the transfer (Conduit), as it was done

Everything here is a person's work (done by Claude in this session on David's behalf, with his written permission of
2026-10-29 to build and run Conduit), counted, never attributed to Unbidden. Times are wall-clock.

| Step | Time | Notes |
|---|---|---|
| Choosing the application, reading its repository (stack, CI, schema, tests), writing the protocol | ~25 min | `stage7-transfer.md`, before anything ran |
| Writing the lab preparation (`bench/ecosystem/conduit_lab.py`) | ~15 min | `.env`, a compose override, synthetic data, a read-only role, a token |
| Cloning at the pinned commit; reviewing the effective compose configuration | ~3 min | ports 127.0.0.1 only (the original 8000 and 5432 on every interface replaced), the original `./postgres-data` bind mount replaced by a named volume, no privilege, no Docker socket, labels; no secret printed |
| Building: three compatibility fixes, in the untracked override, the repository unchanged | 13:19-13:28 UTC (~9 min) | (1) `poetry==1.1` now pulls poetry-core 1.9 (no `poetry.core.toml`): pinned 1.1.15 with poetry-core 1.0.8; (2) asyncpg 0.26.0 has no linux/arm64 wheel and the image no compiler: the app image built for linux/amd64 (emulated); (3) `pkg_resources` missing at start (2022 virtualenvs carried setuptools): setuptools 65.5.0 added to the venv |
| Synthetic data, read-only role | ~3 min | my seed overflowed a 32-bit integer (`g * 104729`): cast to bigint. 2,000 users, 20,000 articles, 300,000 comments (at most 15 per article), 20,000 favorites (planned 200,000; the generated pairs repeat); generated, no real person |
| A token for a synthetic user | <1 min | registered through the app's own API; held in `conduit-secrets.env` (mode 600), never printed |
| The workspaces' mandate (`bench/ecosystem/conduit_workspace.py`) and the run harness (`conduit_eval.py`) | ~15 min | grants read-only; experiments in the sandbox (PyPI for dependencies); no PR, merge, deploy or write |

Total human preparation: about 70 minutes, of which about 12 were making a 2022 application build and run today.
Nothing about Conduit was written into Unbidden: no connector, detector, check or fix.
