# Validation protocol, frozen before the run (2026-10-28)

The 32 `validation` repositories of `bench/repos/corpus-2026-10-28.yaml`, never run before and never debugged, run at
the static tier (no model of any kind, US$0) under two versions, paired:

| Version | `unbidden/` tree | Run from |
|---|---|---|
| v0, the program's baseline | `3090aafb67a172bff1e442e616aafa62a007a95e` (commit 1150a66) | a separate worktree at that commit, its own harness |
| v3, frozen | `0c00d9a94c763943f50f93dc8325a43bf7570eb1` | this branch |

Same settings for both: 2 workers, 20 minutes per scan, images created by the run removed after it. Compared with
`bench/compare.py` (one classifier for both, exact McNemar on paired reach outcomes; decisions listed apart).

What counts: reach (stack supported, dependencies installed, an analyzer complete, bootstrapped). The Director's
decisions under v0 are not comparable: v0's `decide` reads the CI anonymously (the defect fixed in v3), and is
reported as such. Nothing in Unbidden changes because of what validation shows; what it suggests becomes a hypothesis
tested on dev.
