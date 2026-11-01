# Installing Unbidden

Unbidden ships as one Python wheel with the web workspace already built inside. The installer puts it in its own
environment with its own Python 3.12 through [uv](https://docs.astral.sh/uv/); nothing else on the machine changes.
The end user needs no Node, no Python, no Docker to install it.

## One line

> **Available once the first release is published.** There is no release on GitHub yet, so this line fails today with
> "no published release found". Until then use the [local-artifact procedure](#installing-from-local-artifacts) below.

```sh
curl -LsSf https://github.com/satisfymath/unbidden-ai/releases/latest/download/install.sh | sh
```

What it does, in order: detects the platform; finds `uv` or asks to install it with its official installer; downloads
`unbidden_ai-X.Y.Z-py3-none-any.whl` and `SHA256SUMS` from the release; verifies the sha256 and refuses on a mismatch;
runs `uv tool install --python 3.12 --reinstall` on the wheel; tells you if the tool directory is not on your PATH.
It never uses `sudo` and never prints a secret.

Then:

```sh
cd your-repo && unbidden
```

## Prerequisites, in three groups

Keep these apart: installing the tool, enabling what each function needs, and where the project's own code runs.

### 1. Installing Unbidden

| Need | Why |
|---|---|
| a shell, `curl`, `shasum` (macOS) or `sha256sum` (Linux) | the installer itself |
| `uv` (installed on request, ~15 MB) | runs the tool in its own environment and brings Python 3.12 (~30 MB, once) |
| ~1 MB download; ~136 MB installed with its dependencies (scipy, numpy, pydantic, psycopg) | the wheel and its environment |

No Docker, Ollama, GitHub token or model key is needed to install, to run `unbidden --version`, `unbidden init`,
`unbidden doctor` or to open the web workspace on the demo.

### 2. Preparing dependencies for functions

Each capability has one dependency; `unbidden doctor` reports every one of them.

| Function | Needs | Notes |
|---|---|---|
| sandbox, `scan`, checks, experiments, probes | Docker running (`docker info` succeeds) | the project's code only ever runs inside it |
| local inference (profiles `local`, `local-first`) | Ollama reachable at `http://localhost:11434` with a model | `unbidden doctor --fix` pulls the recommended one |
| remote inference (`local-first`, `frontier`) | `MODEL_API_KEY` in the repository's `.env` | spend is capped by the mandate and recorded in `~/.unbidden` |
| opening pull requests | `GITHUB_TOKEN` in `.env` | nothing else talks to GitHub with credentials |

Local model sizes, as `unbidden/brain/hardware.py` recommends them (weights plus a 32k-token cache; the machine keeps
up to 10 GB for Docker and the system):

| Model | Loaded | Where |
|---|---|---|
| `muse-glimmer:30b-mxfp8-dflash` / `muse-glimmer:30b-q8_0` | 42 GB / 38 GB | Apple Silicon / GGUF |
| `muse-glimmer:30b-mlx` / `muse-glimmer:30b-q4_K_M` | 24 GB / 22 GB | Apple Silicon / GGUF |
| `llama3.1:8b` | 6.5 GB | both |
| `llama3.2:3b` | 3 GB | both |

### 3. Running the project's code

The repository you point Unbidden at is never executed on your machine directly: builds, checks and experiments run
in the sandbox (`unbidden/sandbox/provision.py`), which is why Docker is the one dependency of every function that
touches code.

## Update, rollback, uninstall

```sh
unbidden update                     # the latest published release
unbidden update --version 0.9.0     # a fixed version: also how you roll back after a failed update
unbidden uninstall                  # shows what would happen
unbidden uninstall --yes            # uv tool uninstall unbidden-ai; data stays
unbidden uninstall --purge --yes    # also deletes ~/.unbidden and this repository's .unbidden/ (listed first)
```

`update` runs the same `install.sh` that is shipped inside the package (`unbidden/distribution/install.sh`), so the
checksum gate and the Python 3.12 pin are identical. The two commands live in `unbidden/distribution/` and appear in
the CLI once `cli.build_parser` calls its `register`; until then the installer's own flags below do the same job. Your data (`~/.unbidden`, and `.unbidden/` in each repository: mandate, store, records) is never
touched by an install, update or plain uninstall. The same is true of the installer's own flags:
`sh install.sh --version <previous>` and `sh install.sh --uninstall`.

## PATH

`uv tool install` puts the `unbidden` executable in uv's tool bin directory (`uv tool dir --bin`, usually
`~/.local/bin`). If that directory is not on your PATH the installer prints the exact line; or let uv do it with
`uv tool update-shell`.

| Shell | Line |
|---|---|
| zsh | `echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc && source ~/.zshrc` |
| bash | `echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && source ~/.bashrc` |
| fish | `fish_add_path ~/.local/bin` |

## Platform support

| Platform | Status |
|---|---|
| macOS on Apple Silicon (arm64) | tested natively: install, `--version`, idempotent rerun, checksum refusal, web workspace from the installed tool, uninstall keeping data |
| Linux x86-64, glibc >= 2.28 | tested on a GitHub Actions `ubuntu-latest` runner by `.github/workflows/release.yml` (`smoke-linux-x86_64`), the authoritative Linux check |
| macOS on Intel, Linux arm64, Windows, musl | untested; the installer stops with a message. A source install with `uv` may work |

The wheel is pure Python; the native pieces (scipy, numpy, pydantic-core, google-re2, psycopg-binary) come from PyPI
as prebuilt wheels for those two platforms, which is what the support table reflects. An x86-64 VM on Apple Silicon
runs under emulation and is not counted as a Linux test.

## Installing from local artifacts

This is how the installer is tested, and how to install before any release exists. Build the files
(`make dist`: builds the frontend with Node 24, then `uv build` and `SHA256SUMS`), serve the directory, point the
installer at it. `http://` is accepted only for loopback addresses.

```sh
make dist                                   # dist/unbidden_ai-0.9.0-py3-none-any.whl, .tar.gz, SHA256SUMS
(cd dist && python3 -m http.server 8777 --bind 127.0.0.1 &)
UNBIDDEN_INSTALL_BASE=http://127.0.0.1:8777 sh install.sh --yes --version 0.9.0
unbidden --version                          # unbidden 0.9.0
```

To try it without touching your real environment, give the installer a throwaway home:

```sh
export HOME=$(mktemp -d) UV_TOOL_DIR=$HOME/tools UV_TOOL_BIN_DIR=$HOME/bin
```

Environment the installer reads: `UNBIDDEN_VERSION` (same as `--version`), `UNBIDDEN_INSTALL_BASE` (where the wheel
and `SHA256SUMS` live; default: the GitHub release of that version), `UNBIDDEN_REPO` (default
`satisfymath/unbidden-ai`), and uv's own `UV_TOOL_DIR`, `UV_TOOL_BIN_DIR`, `UV_INSTALL_DIR`.

Exit codes: 2 bad usage, 3 unsupported platform, 4 uv declined, 5 no release found, 6 download failed, 7 wheel not
listed in `SHA256SUMS`, 8 checksum mismatch, 9 the installed command reports another version.
