"""Measurement against the application as the project runs it (stage 10, `served` mode; see `prepare.py`).

One session is one sandbox run beside a fresh database: the sandbox starts the project's server command with the
project's environment, Unbidden (on the host) waits for it to answer, seeds the database from its catalog
(`seed.py`), resets the engine's statement statistics, then a fixed driver sends the declared request: warm-up, then
the timed calls. Nothing in the measured path is written by a model; a model only chooses the request, and the
engine says whether that request did what it claims (`validate`).
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from unbidden.lab.prepare import ServerRecipe
from unbidden.lab.seed import Psql, SeedPlan, data_check, reads_by, statements_using
from unbidden.observe.compose import Service
from unbidden.sandbox.provision import DependencyImage, sandbox_spec
from unbidden.sandbox.runner import SandboxResult, SandboxRunner
from unbidden.sandbox.sidecars import Sidecars, data_services

LAB_DIR = ".unbidden-lab"
READY_TIMEOUT_S = 240
DRIVER = '''"""Unbidden's served driver: fixed code, never written by a model. Standard library only."""
import hashlib, http.client, json, os, socket, sys, time, urllib.parse

LAB = "/work/{lab}"
port, warmup, samples = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])


def out(data):
    with open(LAB + "/result.json", "w") as f:
        json.dump(data, f)


deadline = time.time() + {ready}
while True:
    try:
        socket.create_connection(("127.0.0.1", port), timeout=1).close()
        break
    except OSError:
        if time.time() > deadline:
            out({{"error": "the server did not listen on port %d within {ready} s" % port}})
            sys.exit(0)
        time.sleep(0.5)
open(LAB + "/ready", "w").close()
deadline = time.time() + 1800
while not os.path.exists(LAB + "/seeded"):
    if os.path.exists(LAB + "/abort") or time.time() > deadline:
        out({{"error": "aborted before measuring"}})
        sys.exit(0)
    time.sleep(0.3)
req = json.load(open(LAB + "/request.json"))
values = req.get("values") or [""]
conn = http.client.HTTPConnection("127.0.0.1", port, timeout=120)


def canonical(data):
    try:
        value = json.loads(data)
    except ValueError:
        return hashlib.sha256(data).hexdigest(), data[:300].decode("utf-8", "replace")

    def norm(v):
        if isinstance(v, dict):
            return {{k: norm(x) for k, x in sorted(v.items())}}
        if isinstance(v, list):
            return sorted((norm(x) for x in v), key=lambda x: json.dumps(x, sort_keys=True))
        return v

    text = json.dumps(norm(value), sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest(), text[:300]


def call(i):
    value = str(values[i % len(values)])
    path = req["path"].replace("{{value}}", urllib.parse.quote(value, safe=""))
    query = {{k: str(v).replace("{{value}}", value) for k, v in (req.get("query") or {{}}).items()}}
    if query:
        path += "?" + urllib.parse.urlencode(query)
    body = req.get("body")
    payload = json.dumps(body).replace("{{value}}", value).encode() if body is not None else None
    headers = {{"Content-Type": "application/json"}} if payload is not None else {{}}
    conn.request(req["method"], path, body=payload, headers=headers)
    response = conn.getresponse()
    return response.status, response.read()


warm = [call(i)[0] for i in range(warmup)]
latencies, statuses, digests, first = [], [], [], ""
for i in range(warmup, warmup + samples):
    started = time.perf_counter()
    status, data = call(i)
    latencies.append((time.perf_counter() - started) * 1000)
    statuses.append(status)
    digest, text = canonical(data)
    digests.append(digest)
    first = first or text
out({{"latencies_ms": latencies, "statuses": statuses, "warmup_statuses": warm, "digests": digests, "sample": first}})
'''


def psql_for(container: str, user: str, database: str, docker: str = "docker") -> Psql:
    def run(sql: str) -> str:
        done = subprocess.run([docker, "exec", "-i", container, "psql", "-U", user, "-d", database, "-v",
                               "ON_ERROR_STOP=1", "-q", "-At", "-F", "\t"], input=sql, capture_output=True, text=True,
                              check=False)  # fmt: skip
        if done.returncode != 0:
            raise RuntimeError(done.stderr.strip()[-600:] or f"psql exited {done.returncode}")
        return done.stdout

    return run


def postgres_of(sidecars: Sidecars | None, services: list[Service]) -> Psql | None:
    """psql in a session's PostgreSQL, as the database's own user, in its own database."""
    for service in services:
        if sidecars is None or service.data_kind != "postgres" or service.name not in sidecars.names:
            continue
        user = service.environment.get("POSTGRES_USER", "postgres")
        return psql_for(sidecars.names[service.name], user, service.environment.get("POSTGRES_DB", user))
    return None


@dataclass
class Session:
    samples_ms: list[float] | None = None
    statuses: list[int] = field(default_factory=list[int])
    digests: list[str] = field(default_factory=list[str])
    sample: str = ""
    statements: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    scans: int | None = None
    data: str = ""
    data_ok: bool = False
    error: str = ""


def run_session(
    runner: SandboxRunner,
    image: DependencyImage,
    work: Path,
    recipe: ServerRecipe,
    request: dict[str, Any],
    seed: Callable[[Psql], SeedPlan],
    *,
    warmup: int,
    samples: int,
    index: tuple[str, str] | None,
    scans: Callable[[Sidecars, list[Service], str, str], int | None],
    timeout_s: float = 1800,
) -> Session:
    """One served session in `work` (a snapshot with the side's files already written)."""
    lab = work / LAB_DIR
    lab.mkdir(exist_ok=True)
    lab.chmod(0o777)
    for name in ("ready", "seeded", "abort", "result.json", "request.json"):
        (lab / name).unlink(missing_ok=True)
    (lab / "served_driver.py").write_text(DRIVER.format(lab=LAB_DIR, ready=READY_TIMEOUT_S))
    for placeholder in recipe.placeholders:
        (work / placeholder).mkdir(parents=True, exist_ok=True)
    database = recipe.database
    session = Session()
    with data_services([database], statements=True) as sidecars:
        assert sidecars is not None
        psql = postgres_of(sidecars, [database])
        assert psql is not None
        command = f"cd /work && ({recipe.command}) > /work/{LAB_DIR}/server.log 2>&1 & " \
                  f"exec python /work/{LAB_DIR}/served_driver.py {recipe.port} {warmup} {samples}"  # fmt: skip
        spec = sandbox_spec(image, ["bash", "-c", command], public_env=dict(recipe.env), timeout_s=timeout_s,
                            network=sidecars.network)  # fmt: skip
        box: list[SandboxResult] = []
        thread = threading.Thread(target=lambda: box.append(runner.run(spec, work)), daemon=True)
        thread.start()
        deadline = time.monotonic() + READY_TIMEOUT_S + 30
        while not (lab / "ready").exists() and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.5)
        if not (lab / "ready").exists():
            (lab / "abort").touch()
            thread.join(60)
            log = (lab / "server.log").read_text(errors="replace")[-1500:] if (lab / "server.log").exists() else ""
            session.error = f"the application did not start as the project starts it: {log or 'no output'}"
            return session
        try:
            plan = seed(psql)
            for statement in plan.statements:
                psql(statement)
            session.data_ok, session.data = data_check(psql, plan)
            values: list[str] = []
            if request.get("values_sql"):
                values = [ln.split("\t")[0] for ln in psql(str(request["values_sql"])).splitlines() if ln.strip()]
            calls = warmup + samples
            if request.get("values_sql") and (not values or (request.get("method") != "GET" and len(values) < calls)):
                # Sent anyway, an empty value makes `/vendor/{value}` into `/vendor/` (stage 10: a redirect on every
                # call, read as the request's failure); a write needs a target per call.
                raise ValueError(f"the request's values query returned {len(values)} row(s), {calls} needed "
                                 f"(seeded: {session.data})")  # fmt: skip
            psql("CREATE EXTENSION IF NOT EXISTS pg_stat_statements; SELECT pg_stat_statements_reset();")
        except (RuntimeError, ValueError) as exc:
            (lab / "abort").touch()
            thread.join(60)
            session.error = (f"the request cannot be sent: {exc}" if "values query" in str(exc)
                             else f"seeding the database failed: {exc}")  # fmt: skip
            return session
        (lab / "request.json").write_text(json.dumps({**request, "values": values}))
        (lab / "seeded").touch()
        thread.join(timeout_s)
        if index is not None:
            session.scans = scans(sidecars, [database], *index)
        if index is not None or request.get("table"):
            table, column = index or (str(request["table"]), str(request["column"]))
            try:
                session.statements = statements_using(psql, table, column, samples)
            except RuntimeError:
                session.statements = []
    out = lab / "result.json"
    if not out.exists():
        result = box[0] if box else None
        session.error = f"the driver wrote no result ({(result.stdout + result.stderr)[-600:] if result else ''})"
        return session
    data = json.loads(out.read_text())
    if data.get("error"):
        log = (lab / "server.log").read_text(errors="replace")[-1200:] if (lab / "server.log").exists() else ""
        session.error = f"{data['error']}: {log}"
        return session
    session.samples_ms = [float(x) for x in data["latencies_ms"]]
    session.statuses = [int(s) for s in [*data.get("warmup_statuses", []), *data["statuses"]]]
    session.digests = list(data["digests"])
    session.sample = str(data.get("sample", ""))
    return session


def nonempty(sample: str) -> bool:
    """Whether a response carries data: not an empty list, and not an object whose lists are all empty."""
    try:
        value = json.loads(sample)
    except ValueError:
        return bool(sample.strip())
    if isinstance(value, list):
        return bool(value)
    if isinstance(value, dict):
        lists = [v for v in value.values() if isinstance(v, list)]
        return any(lists) if lists else bool(value)
    return value not in (None, "", 0)


def validate(session: Session, table: str, column: str, samples: int, *, reads: bool) -> tuple[bool, list[str]]:
    """Before any comparison, at the base: the workload ran without help, did the operation it claims (the engine ran a
    statement on `table` by `column` on every measured call), on the data it needs, with a functional result."""
    problems: list[str] = []
    if session.error:
        return False, [session.error]
    bad = [s for s in session.statuses if not 200 <= s < 300]
    if bad:
        problems.append(f"{len(bad)} of {len(session.statuses)} calls failed (HTTP {sorted(set(bad))})")
    if not session.data_ok:
        problems.append(f"the data is not what the measurement needs: {session.data}")
    used = [s for s in session.statements if int(s["calls"]) >= samples and reads_by(str(s["query"]), table, column)]
    if not used:
        seen = "; ".join(str(s["query"])[:160] for s in session.statements[:2]) or "none on that table and column"
        problems.append(f"the calls did not run a statement that reads {table} by {column} on every call ({seen})")
    if reads and not nonempty(session.sample):
        problems.append(f"the request returned no data (first response: {session.sample[:160]!r})")
    if reads and len(set(session.digests)) > max(1, len(session.digests) // 2) and not session.statements:
        problems.append("the same request returned different results on repeated calls")
    return not problems, problems


def same_results(base: list[Session], candidate: list[Session]) -> tuple[bool | None, str]:
    """Whether both sides answered the same: the sequence of response digests of every session (same data, same
    requests in the same order). None when a side has no digest."""

    def runs(sessions: list[Session]) -> set[tuple[str, ...]]:
        return {tuple(s.digests) for s in sessions if s.digests}

    b, c = runs(base), runs(candidate)
    if not b or not c:
        return None, "no response was recorded on one side"
    if b == c:
        return True, f"the same {len(next(iter(b)))} responses on both sides, in every session"
    differing = sum(1 for i, d in enumerate(next(iter(c))) if d != next(iter(b))[i]) if len(b) == len(c) == 1 else -1
    return False, f"{differing if differing >= 0 else 'some'} responses differ between base and candidate"


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


_PATH_VALUE = re.compile(r"\{[^}]+\}")
