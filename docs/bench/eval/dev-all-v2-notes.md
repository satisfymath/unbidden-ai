# Dev, all 40 at v2 (`unbidden/` tree d2e92d2): notes added after the run

Record: `dev-all-v2.json`, as produced.

**Valid:** reach. Batch 1, v0 to v2: bootstrapped 8/15 to 13/15 (5 gained, 0 lost, exact McNemar p = 0.0625). Batch 2,
v1 to v2: 5/15 to 6/15 (1 gained, 0 lost). No repository went backwards in reaching an analysis.

**Not valid:** the Director's decisions. Every row has `ci_status: None`. `unbidden decide`, which the static tier
uses, did not load Unbidden's credentials and asked GitHub anonymously; the anonymous limit (60 an hour) was spent, and
an unreadable CI looked the same as a commit without checks. The rule that declines findings a green CI does not
report could not fire, so repositories that v1 declined correctly (Cirq, tpu-inference, vscode-beads) appear as
"actionable" here, and Effect-TS, marko and Radarr as hundreds of experiments. Counted as what they are: false
positives the Director would have pursued for want of the CI's verdict. The autonomous cycle (`watch`) loads
credentials and was not affected. Fixed in v3: `decide` loads them, an unreadable CI is reported with its cause, and
the Director waits instead of experimenting when the CI runs the tool and its verdict cannot be read.

Root causes at v2 (one classifier, recomputed from the records): unsupported_language 15 (Go, Rust, Java, Ruby, PHP,
Kotlin), actionable 13 (see above), nothing_found 5, findings_declined 2, and one each of deps_resolution
(IsaacCapture: its local package depends on the project itself), deps_vcs_source (a git dependency; the mandate grants
no such network), no_dependency_manifest (squid-sdk, Rush), deps_tool_version (codexmate: corepack took the newest
pnpm, which the project's Node could not run; fixed in v3 by taking pnpm from the lockfile's format) and
no_applicable_analyzer (mapng: Vue without tsconfig or ESLint).
