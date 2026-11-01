# Stage 8: the release walk from a clean checkout

`stage8-release-walk/walk.sh` is the script: a new empty HOME, a fresh HTTPS clone, and only `RELEASE.md`'s
commands, each logged with its exit code and time. The only thing taken from the machine user's HOME is Docker's
plugin directory (`~/.docker/cli-plugins`, installed by OrbStack; without it there is no `docker compose`). No Meta
key and no GitHub token in that HOME: the run uses local models only. Paths of the scratch directory are replaced
by `<scratch>` in the logs.

| Walk | Commit | Result | Changed after it |
|---|---|---|---|
| 1 | d0db3d3 | `make check` failed: the pyright package's Node download; then the labs could not start (`docker compose` absent without Docker's plugin directory) | `pyright[nodejs]` in the lock; a test's type error fixed; RELEASE names OrbStack and the compose plugin as a prerequisite; the plugin directory linked in the walk |
| 2 | 2f8cf08 | install and checks ok; the board app did not answer within its wait (not reproduced twice since); its `down` removed other labs' containers (Conduit's, LNbits'; volumes kept, both restored) | `down` limited to `unbidden-lab-*` containers |
| 3 | 2f8cf08 | every step ok; the cycle accepted, the checker found no problem | — |
| 4 | 36e1a59 (the candidate) | every step ok; other labs' containers untouched | — |
