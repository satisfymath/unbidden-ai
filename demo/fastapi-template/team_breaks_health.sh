#!/usr/bin/env bash
# Scenario, played by this script and declared as such: the team deploys a release whose health check fails.
# It commits locally in the deployment checkout (nothing is pushed) and deploys with the team's usual steps.
# Unbidden is expected to see the outage, roll back to the last healthy version on its own, and set a hold.
set -euo pipefail
cd "${1:?usage: team_breaks_health.sh <deployment checkout>}"
python3 - <<'PY'
from pathlib import Path
p = Path("backend/app/api/routes/utils.py")
s = p.read_text()
marker = "async def health_check() -> bool:\n"
assert marker in s, "health check not found"
s = s.replace(marker, marker + '    raise RuntimeError("scenario: release 1.6 broke the database pool")\n', 1)
p.write_text(s)
PY
git -c user.name="Team (scenario)" -c user.email=team@example.com commit -qam "release 1.6 (scenario: breaks the health check)"
echo "team deploys $(git rev-parse --short HEAD)"
docker compose up -d --build backend
