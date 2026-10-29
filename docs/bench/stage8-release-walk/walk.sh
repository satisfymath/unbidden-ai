#!/bin/zsh
# The release walk: a fresh HOME (no ~/.unbidden, no keys, no caches), a fresh directory, only RELEASE.md's commands.
export HOME=$(mktemp -d <scratch>/home.XXXX)
export PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
cd $HOME
# Declared: the only thing taken from the machine user's HOME is Docker's own plugin link (its compose plugin).
mkdir -p $HOME/.docker && ln -s <user home>/.docker/cli-plugins $HOME/.docker/cli-plugins
step() { echo "\n### $*"; local t=$SECONDS; eval "$@" 2>&1 | tail -${TAILN:-25}; echo "### exit ${pipestatus[1]} in $((SECONDS-t)) s"; }
step git clone -q https://github.com/satisfymath/unbidden-ai.git
cd unbidden-ai
step git checkout -q 36e1a59
step uv sync -q
TAILN=6 step make check
step uv run unbidden doctor
step uv run unbidden spend
step uv run python -m bench.ecosystem.depot_lab up
step uv run python -m bench.ecosystem.board_lab reset style
step uv run python -m bench.ecosystem.board_workspace "$PWD" --policy local --perception dom
TAILN=40 step '(cd ~/unbidden-lab/boardapp && uv run --project "$OLDPWD" unbidden watch --once)'
step uv run python -m bench.ecosystem.board_check
step '(cd ~/unbidden-lab/boardapp && uv run --project "$OLDPWD" unbidden activity)'
step '(cd ~/unbidden-lab/boardapp && uv run --project "$OLDPWD" unbidden connections)'
step '(cd ~/unbidden-lab/boardapp && uv run --project "$OLDPWD" unbidden egress)'
step '(cd ~/unbidden-lab/boardapp && uv run --project "$OLDPWD" unbidden kill)'
step '(cd ~/unbidden-lab/boardapp && uv run --project "$OLDPWD" unbidden resume)'
step 'uv run python -m bench.ecosystem.board_lab down && uv run python -m bench.ecosystem.depot_lab down'
step docker ps -a --filter label=unbidden.sandbox --format '{{.Names}}'
step docker ps -a --filter label=unbidden.lab=ecosystem --format '{{.Names}}'
echo "HOME was $HOME"
step docker ps --format "{{.Names}}" --filter name=conduit-staging --filter name=lnbits-staging
