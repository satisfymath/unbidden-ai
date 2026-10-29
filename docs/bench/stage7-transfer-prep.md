# Stage 7: human preparation for the transfer (Conduit), as it is done

Everything here is a person's work (done by Claude in this session on David's behalf), counted, never attributed
to Unbidden.

| Step | Time | Status |
|---|---|---|
| Choosing the application, reading its repository (stack, CI, schema, tests), writing the protocol | ~25 min | done (`stage7-transfer.md`) |
| Cloning at the pinned commit | <1 min | done (`~/unbidden-lab/real/fastapi-realworld-example-app`, read only) |
| Writing the lab preparation (`bench/ecosystem/conduit_lab.py`: `.env`, a compose override for 127.0.0.1 and a named volume, synthetic data, a read-only role, a token for a synthetic user) | ~15 min | written, **not run** |
| Building and starting the application | — | **blocked**: building and running a third-party repository was refused by this session's permission rules; it needs David's explicit permission |
| Synthetic data, read-only role, token | — | not done (depends on the above) |
| Workspace: mandate, grants, priorities, goal, deploy and check steps | — | not done |

Nothing of Conduit has been run, and the agent has not seen it.
