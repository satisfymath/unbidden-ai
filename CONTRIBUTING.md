# Contributing to Unbidden

Thanks for helping. Bugs, measurements that contradict a claim, and focused pull requests are all welcome. For a large
change, open an issue first so the design can be agreed before the work is done.

To report a vulnerability, follow [`SECURITY.md`](SECURITY.md) instead. Everyone taking part follows the
[Code of Conduct](CODE_OF_CONDUCT.md).

## Set up

You need Python 3.12 through [uv](https://docs.astral.sh/uv/), and Docker for anything that touches the sandbox.
Node 24 is needed only for the web workspace in `frontend/`.

```sh
make setup       # install the development environment
make check       # ruff, pyright, pytest
make web-check   # the web workspace's checks
make dist        # the wheel with the web workspace inside, and SHA256SUMS
```

The tests need no model key. Copy `.env.example` to `.env` only to run against real models; `.env` is ignored by git, and
CI scans every push for secrets.

## Pull requests

1. Branch from an up-to-date `main`, one unit of work per branch.
2. Keep `make check` green, and add a test that pins the behavior you changed.
3. Title the pull request as a [Conventional Commit](https://www.conventionalcommits.org/): `fix(lab): ...`,
   `feat(observe): ...`, `docs: ...`.
4. Update the docs that describe what you changed. A design choice with a measurement behind it goes in
   [`docs/DECISIONS.md`](docs/DECISIONS.md).

## The rule for claims

Unbidden only claims what it measured, and the project holds itself to the same rule. If a change makes something
faster, safer or more accurate, the pull request shows what was run and what came out, including the results that
went against it. A claim's confidence is capped by its [evidence level](README.md#evidence-levels).

Never weaken a test, a gate or a guarantee to get a result through. If one is wrong, change it in its own pull request and
say why.

## License

By contributing, you agree that your contribution is licensed under the [Apache License 2.0](LICENSE), as section 5 of the
license provides.
