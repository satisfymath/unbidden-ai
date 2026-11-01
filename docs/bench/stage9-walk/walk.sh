#!/bin/zsh
# Stage 9 release walk: an empty HOME, a fresh HTTPS clone of the candidate, only RELEASE.md's commands. No Meta key
# and no local model in that HOME (stage 9 uses Meta's API only, and the key is not copied): the run's model calls
# are refused with their reason. Declared: Docker's plugin directory is linked from the machine user's HOME.
export HOME=$(mktemp -d "$WALKDIR/home.XXXX")
export PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
mkdir -p $HOME/.docker && ln -s "$REALHOME/.docker/cli-plugins" $HOME/.docker/cli-plugins
cd $HOME
step() { echo "\n### $*"; local t=$SECONDS; eval "$@" 2>&1 | tail -${TAILN:-25}; echo "### exit ${pipestatus[1]} in $((SECONDS-t)) s"; }
step git clone -q https://github.com/satisfymath/unbidden-ai.git
cd unbidden-ai
step git checkout -q "$CANDIDATE"
step uv sync -q
TAILN=4 step make check
step uv run unbidden doctor
step uv run unbidden spend
step uv run python -m bench.ecosystem.depot_lab up
step uv run python -m bench.ecosystem.board_lab reset style
U="uv run --project $HOME/unbidden-ai unbidden"
step "(cd ~/unbidden-lab/boardapp && $U init)"
cat > ~/unbidden-lab/boardapp/.unbidden/mandate.yaml <<'YAML'
mandate:
  workspace: boardapp
  priorities: [correctness, performance of reads as data grows]
  business_constraints: {maximum_monthly_spend_usd: 2.0}
  autonomy: {observe: allow, run_experiments: allow, provision_dependencies: allow, delegate_synthetic: allow,
             use_new_capabilities: allow, open_pull_requests: deny, merge_pull_requests: deny, deploy: deny,
             rollback: deny, act_on_connections: deny}
  egress: {package_registries: [pypi.org, files.pythonhosted.org],
           remote_models: {destinations: [api.meta.ai], max_payload_bytes: 60000}}
  models: {profile: frontier, local_fallback: deny, local_inference: deny}
YAML
TAILN=40 step "(cd ~/unbidden-lab/boardapp && $U watch --once)"
TAILN=40 step "(cd ~/unbidden-lab/boardapp && $U activity)"
step "(cd ~/unbidden-lab/boardapp && $U connections)"
step "(cd ~/unbidden-lab/boardapp && $U egress)"
step "(cd ~/unbidden-lab/boardapp && $U kill)"
step "(cd ~/unbidden-lab/boardapp && $U resume)"
step "uv run python -m bench.ecosystem.board_lab down && uv run python -m bench.ecosystem.depot_lab down"
step docker ps -a --filter label=unbidden.sandbox --format '{{.Names}}'
step docker ps --format '{{.Names}}' --filter name=conduit-staging --filter name=lnbits-staging --filter name=spoolman-staging --filter name=prefect-staging
