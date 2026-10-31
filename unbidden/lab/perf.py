"""PerfLab: measure a performance opportunity on both sides, with criteria fixed before measuring.

1. The local model writes a candidate (the schema change, as this repository makes schema changes).
2. The local model writes a workload: synthetic data and one request to an affected endpoint.
3. Our fixed driver runs it at the base and at the candidate, each side in its own sandbox with fresh
   services, after the repository's own CI setup steps (migrations included): warm-up, then samples.
4. Mann-Whitney, effect size and a bootstrap interval decide; the CI test job runs on both sides too.
"""

from __future__ import annotations

import hashlib
import json
import re
import statistics
import subprocess
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from unbidden.brain.codeblocks import CodeBlockError, parse_files
from unbidden.brain.prompts import load_prompt
from unbidden.brain.providers import ProviderError
from unbidden.brain.router import Brain, BrainError
from unbidden.contracts.common import EvidenceRef, utc_now
from unbidden.contracts.events import Event, EventType
from unbidden.contracts.experiment import Experiment, ExperimentSpec, TestOutcome, Verdict
from unbidden.contracts.llm import LLMRequest, Message, Tier
from unbidden.contracts.opportunity import Opportunity, OpportunityStatus
from unbidden.guardian.scanner import redact_text
from unbidden.lab.evaluator import classify_tests, level_for
from unbidden.lab.fixlab import Candidate, unified_patch
from unbidden.lab.perfstats import (
    CONTROL_SESSIONS,
    MIN_EFFECT,
    PROMOTION_CRITERIA,
    SESSIONS_PER_ARM,
    judge_promotion,
    judge_sessions,
)
from unbidden.lab.prepare import ServerRecipe, inventory
from unbidden.lab.seed import Psql, SeedPlan, describe, plan_seed, reads_by, statements_using
from unbidden.lab.served import Session, nonempty, postgres_of, run_session, validate
from unbidden.lab.testsuite import TestPlan, run_suite, test_plan
from unbidden.observe.ci import ci_test_plan
from unbidden.observe.stack import Stack
from unbidden.provenance import provenance
from unbidden.sandbox.provision import DependencyImage, link_dependencies, sandbox_spec
from unbidden.sandbox.runner import SandboxRunner, discard, snapshot
from unbidden.sandbox.sidecars import data_services
from unbidden.sandbox.tools import tools_for

ACTOR = "lab"
LAB_DIR = ".unbidden-lab"
SAMPLES = 20
WARMUP = 3
SEED_ROWS = 200_000
SEED_OWNERS = 2_000
Progress = Callable[[str], None]

DRIVER_TEST = "test_unbidden_workload"
DRIVER = f'''"""Unbidden's measurement driver: fixed code, never written by a model.

It runs as one more test inside the repository's own CI test command, so it gets exactly the environment,
fixtures and configuration the team's tests get.
"""
import importlib.util, inspect, json, time
from pathlib import Path


def _status(r):
    return r if isinstance(r, int) else getattr(r, "status_code", getattr(r, "status", None))


def _digest(r):
    """The response's content, canonical: the same data gives the same digest, whatever the order of a list."""
    import hashlib
    import re
    body = getattr(r, "content", None)
    if body is None or isinstance(r, int):
        return None, ""
    try:
        value = json.loads(body)
    except ValueError:
        return hashlib.sha256(body).hexdigest(), body[:300].decode("utf-8", "replace")

    # Identifiers and times the application generates differ between sessions with the same data (fst, stage 10:
    # uuid4 ids and creation times made every base session answer differently): compared as "generated".
    GENERATED = re.compile(
        r"[0-9a-fA-F]{{8}}-[0-9a-fA-F]{{4}}-[0-9a-fA-F]{{4}}-[0-9a-fA-F]{{4}}-[0-9a-fA-F]{{12}}"
        r"|\\d{{4}}-\\d{{2}}-\\d{{2}}[T ]\\d{{2}}:\\d{{2}}(:\\d{{2}}(\\.\\d+)?)?(Z|[+-]\\d{{2}}:?\\d{{2}})?"
    )

    def norm(v):
        if isinstance(v, dict):
            return {{k: norm(x) for k, x in sorted(v.items())}}
        if isinstance(v, list):
            return sorted((norm(x) for x in v), key=lambda x: json.dumps(x, sort_keys=True))
        if isinstance(v, str) and GENERATED.fullmatch(v):
            return "<generated>"
        return v

    text = json.dumps(norm(value), sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest(), text[:300]


def {DRIVER_TEST}(request):
    spec = importlib.util.spec_from_file_location("unbidden_workload", "/work/{LAB_DIR}/workload.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # build()'s parameters are the suite's own fixtures, by name (`def build(api_client, unique_user)`).
    fixtures = {{name: request.getfixturevalue(name) for name in inspect.signature(module.build).parameters}}
    call = module.build(**fixtures)
    for _ in range({WARMUP}):
        status = _status(call())
        assert status == 200, f"warm-up returned HTTP {{status}}"
    latencies, digests, sample = [], [], ""
    for _ in range({SAMPLES}):
        started = time.perf_counter()
        response = call()
        latencies.append((time.perf_counter() - started) * 1000)
        status = _status(response)
        assert status == 200, f"sample returned HTTP {{status}}"
        digest, text = _digest(response)
        digests.append(digest)
        sample = sample or text
    # The database engine the measurement ran on, from any fixture that holds a session or an engine.
    engine = None
    for value in fixtures.values():
        try:
            bind = value.get_bind() if hasattr(value, "get_bind") else getattr(value, "bind", None) or value
            engine = engine or getattr(getattr(bind, "dialect", None), "name", None)
        except Exception:
            pass
    Path("/work/{LAB_DIR}/result.json").write_text(json.dumps({{"latencies_ms": latencies, "engine": engine,
                                                              "digests": digests, "sample": sample}}))
'''


def async_driver(workload: str, marker: str) -> str | None:
    """The driver for an asynchronous suite (stage 8 regression on Conduit: every workload failed on event loops,
    because a synchronous test cannot use the suite's async fixtures). The fixtures `build` names become the test's
    own parameters, so the suite's plugin resolves them on its loop; `build` and the function it returns may be
    coroutines, and are awaited. Fixed code, generated from the workload's signature; None if it has no `build`."""
    import ast

    try:
        tree = ast.parse(workload)
    except SyntaxError:
        return None
    build = next((n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "build"),
                 None)  # fmt: skip
    if build is None:
        return None
    names = [a.arg for a in build.args.args]
    params = ", ".join(names)
    passed = ", ".join(f"{n}={n}" for n in names)
    return f'''"""Unbidden's measurement driver for an asynchronous suite: fixed code, never written by a model."""
import importlib.util, inspect, json, time
from pathlib import Path

import pytest


def _status(r):
    return r if isinstance(r, int) else getattr(r, "status_code", getattr(r, "status", None))


def _digest(r):
    """The response's content, canonical: the same data gives the same digest, whatever the order of a list."""
    import hashlib
    import re
    body = getattr(r, "content", None)
    if body is None or isinstance(r, int):
        return None, ""
    try:
        value = json.loads(body)
    except ValueError:
        return hashlib.sha256(body).hexdigest(), body[:300].decode("utf-8", "replace")

    # Identifiers and times the application generates differ between sessions with the same data (fst, stage 10:
    # uuid4 ids and creation times made every base session answer differently): compared as "generated".
    GENERATED = re.compile(
        r"[0-9a-fA-F]{{8}}-[0-9a-fA-F]{{4}}-[0-9a-fA-F]{{4}}-[0-9a-fA-F]{{4}}-[0-9a-fA-F]{{12}}"
        r"|\\d{{4}}-\\d{{2}}-\\d{{2}}[T ]\\d{{2}}:\\d{{2}}(:\\d{{2}}(\\.\\d+)?)?(Z|[+-]\\d{{2}}:?\\d{{2}})?"
    )

    def norm(v):
        if isinstance(v, dict):
            return {{k: norm(x) for k, x in sorted(v.items())}}
        if isinstance(v, list):
            return sorted((norm(x) for x in v), key=lambda x: json.dumps(x, sort_keys=True))
        if isinstance(v, str) and GENERATED.fullmatch(v):
            return "<generated>"
        return v

    text = json.dumps(norm(value), sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest(), text[:300]



@pytest.mark.{marker}
async def {DRIVER_TEST}({params}):
    spec = importlib.util.spec_from_file_location("unbidden_workload", "/work/{LAB_DIR}/workload.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    call = module.build({passed})
    if inspect.isawaitable(call):
        call = await call

    async def once():
        response = call()
        return await response if inspect.isawaitable(response) else response

    for _ in range({WARMUP}):
        status = _status(await once())
        assert status == 200, f"warm-up returned HTTP {{status}}"
    latencies, digests, sample = [], [], ""
    for _ in range({SAMPLES}):
        started = time.perf_counter()
        response = await once()
        latencies.append((time.perf_counter() - started) * 1000)
        status = _status(response)
        assert status == 200, f"sample returned HTTP {{status}}"
        digest, text = _digest(response)
        digests.append(digest)
        sample = sample or text
    Path("/work/{LAB_DIR}/result.json").write_text(json.dumps({{"latencies_ms": latencies, "engine": None,
                                                              "digests": digests, "sample": sample}}))
'''


def index_scans(sidecars: Any, services: list[Any], table: str, column: str) -> int | None:
    """Scans of every index led by `table.column` in a session's PostgreSQL, over all its databases, read from the
    engine's statistics once they are flushed. None when the session has no PostgreSQL (the mechanism is then not
    observable here, said as such)."""
    import time as _time

    if not (re.fullmatch(r"\w+", table) and re.fullmatch(r"\w+", column)):
        return None
    for service in services:
        name = sidecars.names.get(service.name)
        if name is None or not re.match(r"(.*/)?(postgres|postgis)\b", service.image or ""):
            continue
        user = service.environment.get("POSTGRES_USER", "postgres")

        def psql(database: str, sql: str, name: str = name, user: str = user) -> str | None:
            ran = subprocess.run(["docker", "exec", name, "psql", "-U", user, "-d", database, "-At", "-c", sql],
                                 capture_output=True, text=True, check=False)  # fmt: skip
            return ran.stdout if ran.returncode == 0 else None

        _time.sleep(1.5)  # the statistics collector flushes at most every 500 ms (PostgreSQL < 15)
        listed = psql(service.environment.get("POSTGRES_DB", user), "SELECT datname FROM pg_database WHERE NOT "
                      "datistemplate") or ""  # fmt: skip
        total = 0
        query = (
            "SELECT COALESCE(SUM(s.idx_scan), 0) FROM pg_stat_user_indexes s JOIN pg_index i ON i.indexrelid = "
            "s.indexrelid JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = i.indkey[0] WHERE "
            f"s.relname = '{table}' AND a.attname = '{column}'"
        )
        for database in listed.split():
            got = psql(database, query)
            total += int(got.strip() or 0) if got is not None else 0
        return total
    return None


def _mechanism(sessions: list[dict[str, Any]], index: tuple[str, str] | None) -> tuple[bool | None, str]:
    """For an index candidate: was an index on the column used on (at least) every measured call of every candidate
    session? None when the change declares no mechanism, or the engine does not show it."""
    if index is None:
        return None, ""
    scans = [s["index_scans"] for s in sessions if s["arm"] == "candidate"]
    if any(x is None for x in scans):
        return None, "index use not observable on this engine"
    low, high = min(scans), max(scans)
    note = f"{low}-{high} scans of an index on {index[0]}.{index[1]} per candidate session (needed: {SAMPLES})"
    return low >= SAMPLES, note


_EMAIL = re.compile(
    r"\b[A-Za-z0-9._%+-]+@(?!example\.(?:com|org|net)\b|test\b|localhost\b)[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)
_IPV4 = re.compile(
    r"\b(?!127\.0\.0\.1\b|0\.0\.0\.0\b|192\.0\.2\.|198\.51\.100\.|203\.0\.113\.)(?:\d{1,3}\.){3}\d{1,3}\b"
)


def mask_personal(text: str) -> str:
    """Email addresses and IP addresses replaced by documentation ones (`person@example.com`, `192.0.2.1`): a test
    fixture's `author@email.com` or a sidecar's address carries nothing a workload needs."""
    return _IPV4.sub("192.0.2.1", _EMAIL.sub("person@example.com", text))


def async_suite(read: Callable[[str], str], files: list[str]) -> str | None:
    """The pytest marker of an asynchronous suite, when its fixtures are coroutines: `asyncio` (pytest-asyncio) or
    `anyio`; None for a synchronous one."""
    conftests = [f for f in files if f.endswith("conftest.py")]
    if not any(re.search(r"^\s*async def \w+\(", read(f), re.M) for f in conftests):
        return None
    declared = " ".join(read(f) for f in ("pyproject.toml", "requirements.txt", "setup.cfg", "poetry.lock")
                        if f in files)  # fmt: skip
    if "pytest-asyncio" in declared or "pytest_asyncio" in declared:
        return "asyncio"
    return "anyio" if "anyio" in declared else None


_REVISION = re.compile(r"^revision\s*(?::\s*str)?\s*=\s*['\"]([^'\"]+)['\"]", re.MULTILINE)
_DOWN = re.compile(r"^down_revision\s*(?::[^=]+)?=\s*['\"]?([^'\"\n]*)['\"]?", re.MULTILINE)


_PARALLEL = re.compile(r"\s(?:-n|--numprocesses)(?:\s+|=)\S+|\s--dist(?:\s+|=)\S+")


def serial(argv: tuple[str, ...]) -> tuple[str, ...]:
    """The team's test command without pytest-xdist's workers: the lab times one selected test, which parallel
    workers cannot speed up, and each worker imports the whole application (mealie's `-n auto` exceeded the
    sandbox's memory before any test ran)."""
    return tuple(
        "\n".join(_PARALLEL.sub("", line) if "pytest" in line else line for line in arg.splitlines()) for arg in argv
    )


def failure_excerpt(output: str, limit: int = 2500) -> str:
    """The lines that say what went wrong (pytest's `E` lines, tracebacks' last frames), not the noise around."""
    lines = output.splitlines()
    keep = [ln for ln in lines if ln.startswith(("E ", "FAILED", "ERROR")) or "Error:" in ln or "error:" in ln]
    tail = "\n".join(lines[-25:])
    excerpt = "\n".join(dict.fromkeys(keep)) + "\n...\n" + tail if keep else tail
    return excerpt[-limit:]


BUILTIN_FIXTURES = frozenset({"request", "tmp_path", "tmp_path_factory", "monkeypatch", "capsys", "caplog",
                              "event_loop", "anyio_backend", "pytestconfig"})  # fmt: skip


def signature_problems(workload: str, visible: set[str]) -> str:
    """Why `build`'s parameters cannot be the suite's fixtures, before anything runs: no `build`, `*args` or
    `**kwargs` (pytest takes them for fixtures named `a`, `kwargs`; stage 10, Spoolman), or a name no conftest
    visible from the workload's directory defines."""
    import ast

    try:
        tree = ast.parse(workload)
    except SyntaxError as exc:
        return f"it is not valid Python ({exc.msg}, line {exc.lineno})"
    build = next((n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "build"),
                 None)  # fmt: skip
    if build is None:
        return "it defines no top-level `build` function"
    if build.args.vararg or build.args.kwarg:
        return "`build` takes *args or **kwargs; name each fixture it needs as a parameter"
    unknown = [a.arg for a in build.args.args if a.arg not in visible]
    if unknown:
        listed = ", ".join(sorted(visible - BUILTIN_FIXTURES)[:40]) or "none"
        return (
            f"`build` asks for {', '.join(unknown)}, which no conftest visible from the tests defines (they define: "
            f"{listed})"
        )
    return ""


def _inserted(psql: Callable[[str], str], tables: list[str]) -> dict[str, int]:
    """Rows inserted into `tables` during the session, every database of the server (the suite may use its own)."""
    names = ", ".join("'" + t.replace("'", "") + "'" for t in tables if re.fullmatch(r"\w+", t))
    if not names:
        return {}
    out: dict[str, int] = {}
    for line in psql(f"SELECT relname, n_tup_ins FROM pg_stat_user_tables WHERE relname IN ({names})").splitlines():
        if "\t" in line:
            name, count = line.split("\t", 1)
            out[name] = out.get(name, 0) + int(count or 0)
    return out


def validate_in_process(
    record: dict[str, Any], relation: tuple[str, str], reads: bool
) -> tuple[bool, list[str], list[str]]:
    """The base run of an in-process workload: did the operation it claims (the engine's statements), on the data it
    needs (rows the engine counted), with a result that can be compared (the response, not only its status)."""
    table, column = relation
    problems: list[str] = []
    passed = [f"the workload ran at the base without help ({len(record['samples_ms'])} measured calls, HTTP 200)"]
    statements = record.get("statements")
    if statements is None:
        passed.append("the engine's statements are not observable here (not PostgreSQL): not verified by the engine")
    elif not [s for s in statements if int(s["calls"]) >= SAMPLES and reads_by(str(s["query"]), table, column)]:
        seen = "; ".join(str(s["query"])[:160] for s in statements[:2]) or "none on that table and column"
        problems.append(f"the calls did not run a statement that reads {table} by {column} on every call ({seen})")
    else:
        passed.append(f"the engine ran a statement reading {table} by {column} on every call")
    inserted = record.get("inserted")
    if inserted is not None:
        rows = inserted.get(table, 0)
        if rows < SEED_ROWS // 2:
            problems.append(f"only {rows} rows were inserted into {table}; seed at least {SEED_ROWS}")
        else:
            passed.append(f"{rows} rows inserted into {table}")
    digests = [d for d in record.get("digests") or [] if d]
    if not digests:
        problems.append("the returned function gives a status code only: return the response object, so the result "
                        "can be compared between base and candidate")  # fmt: skip
    elif reads and not nonempty(str(record.get("sample") or "")):
        problems.append(f"the request returned no data (first response: {str(record.get('sample'))[:160]!r})")
    else:
        passed.append("the response carries data, and its digest is recorded")
    return not problems, problems, passed


def _only_unused(problems: list[str]) -> bool:
    """A base run whose one problem is that no statement used the relation: it ran, on its data, and answered."""
    return len(problems) == 1 and problems[0].startswith("the calls did not run a statement")


def _same(sessions: list[dict[str, Any]]) -> tuple[bool | None, str]:
    """Whether base and candidate answered the same in every session: the sequence of response digests."""
    base = {tuple(s.get("digests") or []) for s in sessions if s["arm"] == "base" and s.get("digests")}
    cand = {tuple(s.get("digests") or []) for s in sessions if s["arm"] == "candidate" and s.get("digests")}
    if not base or not cand or any(None in d for d in base | cand):
        return None, "no response content was recorded on one side"
    if base == cand:
        return True, f"the same {len(next(iter(base)))} responses on both sides, in every session"
    if len(base) > 1:
        return None, "the base itself answered differently from one session to the next: not comparable"
    reference = next(iter(base))
    differing = max(sum(1 for a, b in zip(reference, c, strict=False) if a != b) for c in cand)
    return False, f"{differing} of {len(reference)} responses differ between base and candidate"


@dataclass
class PerfResult:
    experiment: Experiment | None = None
    verdict: Verdict | None = None
    candidate: Candidate | None = None
    notes: list[str] = field(default_factory=list[str])
    blocked: str | None = None  # what Unbidden lacks to run the experiment at all: not an experiment, not a negative
    # The engine showed the endpoints do not look the table up by the column: no opportunity here (verified absence).
    absent: str | None = None


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False).stdout


def alembic_head(repo: Path, rev: str) -> tuple[str, str, str] | None:
    """(migrations directory, head revision, head file) of an Alembic history, read from git."""
    files = [
        f
        for f in _git(repo, "ls-tree", "-r", "--name-only", rev).splitlines()
        if "/versions/" in f and f.endswith(".py")
    ]
    revisions: dict[str, tuple[str, str]] = {}
    for path in files:
        text = _git(repo, "show", f"{rev}:{path}")
        revision, down = _REVISION.search(text), _DOWN.search(text)
        if revision:
            revisions[revision.group(1)] = (path, down.group(1) if down else "")
    referenced = {down for _, down in revisions.values()}
    heads = [r for r in revisions if r not in referenced]
    if len(heads) != 1:
        return None
    path = revisions[heads[0]][0]
    return str(Path(path).parent), heads[0], path


_COLUMN_CALL = re.compile(r"(mapped_column|Column|Field)\(")
_ORM_INSERT = (
    "Insert them with SQLAlchemy Core in bulk, one statement per table with a list of dicts "
    "(`session.execute(insert(Model), rows)`), never one ORM object per row and never database-specific SQL: the "
    "tests may run on SQLite or on Postgres."
)
_ASYNC_RULE = (
    "The application's tests are asynchronous: their fixtures are coroutines. Write `async def build(...)`, await "
    "the fixtures' own async calls, and return an `async def` function that performs the request with the suite's "
    "async client and returns the status code. Never create, get or run an event loop yourself: the test runs on "
    "the suite's loop."
)
_SQL_INSERT = (
    "The application keeps no ORM model of these tables: they are created by the migration shown below, and its "
    "code reads them with SQL. Insert through the same database access the application's tests and code use (its "
    "connection or pool fixture, or its own repository classes), in bulk: one multi-row statement per table, never "
    "one statement per row."
)


def index_candidate(
    show: Callable[[str], str],
    table: str,
    column: str,
    models_file: str,
    head: tuple[str, str, str],
    *,
    model: bool = True,
) -> dict[str, str] | None:
    """The change an unindexed foreign key asks for, written without a model: `index=True` on the column of the
    class mapped to `table`, and an Alembic migration that creates the index after the current head. None when the
    column is not declared on one line, where an edit by pattern would be a guess. A table that no class maps (its
    schema lives only in migrations, `model=False`) gets the migration alone."""
    edited = _model_index(show(models_file), table, column) if model else None
    if model and edited is None:
        return None
    migrations_dir, head_rev, _ = head
    revision = hashlib.sha256(f"{table}.{column}:{head_rev}".encode()).hexdigest()[:12]
    name = f"ix_{table}_{column}"
    migration = _INDEX_MIGRATION.format(table=table, column=column, revision=revision, head_rev=head_rev, name=name)
    migration = in_house_style(migration, show(head[2]))
    out = {f"{migrations_dir}/{revision}_add_index_{table}_{column}.py": migration}
    if edited is not None:
        out[models_file] = edited
    return out


def _model_index(source: str, table: str, column: str) -> str | None:
    """The model file with `index=True` on the column, or None when the edit would be a guess."""
    lines = source.splitlines(keepends=True)
    mapped = next(
        (i for i, x in enumerate(lines) if re.search(rf"__tablename__\s*=\s*[\"']{re.escape(table)}[\"']", x)), None
    )
    if mapped is None:
        return None
    start = max((i for i in range(mapped) if lines[i].startswith("class ")), default=0)
    end = next((i for i in range(mapped, len(lines)) if lines[i].startswith("class ")), len(lines))
    declared = [
        i
        for i in range(start, end)
        if re.match(rf"\s+{re.escape(column)}\s*(:|=)", lines[i]) and _COLUMN_CALL.search(lines[i])
    ]
    if len(declared) != 1:
        return None
    line = lines[declared[0]].rstrip("\n")
    if "index=" in line or not line.rstrip().endswith(")") or line.count("(") != line.count(")"):
        return None
    stripped = line.rstrip()
    lines[declared[0]] = f"{stripped[:-1]}, index=True)\n"
    return "".join(lines)


def in_house_style(migration: str, head: str) -> str:
    """The written migration in the conventions of the project's own latest one, so its linters see nothing new
    (stage 10: Spoolman lints with every ruff rule; a migration without docstrings or return annotations added
    findings, and the index the finding asked for was set aside). Only what the head itself shows is copied: the
    revision variables' annotations, `-> None` on the functions, a docstring in each, a period after the title."""
    out = migration
    for name in ("revision", "down_revision", "branch_labels", "depends_on"):
        declared = re.search(rf"^{name}(\s*:\s*[^=\n]+?)\s*=", head, re.M)
        if declared:
            out = re.sub(rf"^{name} = ", f"{name}{declared.group(1)} = ", out, count=1, flags=re.M)
    if re.search(r"^def upgrade\(\)\s*->\s*None\s*:", head, re.M):
        out = out.replace("def upgrade():", "def upgrade() -> None:").replace(
            "def downgrade():", "def downgrade() -> None:"
        )
    if re.search(r'^def upgrade\([^\n]*:\n\s+"""', head, re.M):
        out = re.sub(r"(def upgrade\([^\n]*:\n)", r'\1    """Add the index."""\n', out)
        out = re.sub(r"(def downgrade\([^\n]*:\n)", r'\1    """Remove the index."""\n', out)
    first = head.lstrip('"').split("\n", 1)[0].strip()
    if first.endswith("."):
        out = re.sub(r'^"""(.+?)\n', lambda m: f'"""{m.group(1).rstrip(".")}.\n', out, count=1)
    return out


# No annotations: `str | None` is a TypeError before Python 3.10, and the project's interpreter may be older
# (Conduit's 3.9 broke the first candidate measured, stage 8 regression B-5).
_INDEX_MIGRATION = '''"""add index on {table}.{column}

Revision ID: {revision}
Revises: {head_rev}

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "{revision}"
down_revision = "{head_rev}"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("{table}", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("{name}"), ["{column}"], unique=False)


def downgrade():
    with op.batch_alter_table("{table}", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("{name}"))
'''


class PerfLab:
    def __init__(
        self,
        repo: Path,
        brain: Brain,
        store: Any,
        stack: Stack,
        images: dict[str, DependencyImage],
        *,
        runner: SandboxRunner | None = None,
        progress: Progress = lambda _: None,
        repairs: int = 4,
    ) -> None:
        self.repo, self.brain, self.store, self.stack, self.images = repo, brain, store, stack, images
        self.runner = runner or SandboxRunner()
        self.progress = progress
        self.repairs = repairs
        self.marker: str | None = None  # the suite's async marker, when its fixtures are coroutines
        self.scans: int | None = None  # index scans in the last measured session (None: not observable)
        self.auth_lines: list[str] = []  # how the example test passes credentials
        self.engine: str | None = None  # the database engine the workload ran on, when the driver could tell
        self.parents: list[str] = []  # the tables the measured one references (their inserted rows are counted)
        self.last_session: Session | None = None  # the last served session, whole
        self.prep_block: tuple[str, str] | None = None  # the readiness state a preparation failed at, and why
        self.unused: list[str] = []  # requests that ran well and whose statements never used the relation

    # Model-written artifacts ----------------------------------------------------------------------------

    async def _ask_files(
        self,
        purpose: str,
        content: str,
        opp: Opportunity,
        sha: str,
        max_tokens: int,
        notes: list[str],
        lab_output: str = "",
    ) -> dict[str, str] | None:
        """Files from the local model, or None with the reason in `notes`. Values in the repository's text that look
        like credentials (a test's `password="password"`) are masked first, as in logs: the prompt still passes
        Guardian's own scan, which refused the whole request when they were left in (stage 8 regression, B-4)."""
        masked = redact_text(content)
        if masked != content:
            note = f"{purpose}: values that look like credentials were masked in the repository's text"
            if note not in notes:
                notes.append(note)
            content = masked
        # What the lab's own sandbox printed (a failed workload's output) is a separate message: it comes from runs
        # on the workload's synthetic data, not from the repository or a running system (stage 9: Conduit's test
        # emails and pytest's ERROR lines in it made the whole request "production data", refused). Personal-looking
        # values are masked in both; Guardian still classifies and scans what is sent.
        content = mask_personal(content)
        messages = [Message(role="user", content=content, source="repo")]
        if lab_output:
            messages.append(Message(role="user", content=mask_personal(redact_text(lab_output)), source="synthetic"))
        try:
            response = await self.brain.complete(
                LLMRequest(
                    purpose=purpose,
                    expect_files=True,
                    tier=Tier.LOCAL,
                    messages=messages,
                    max_tokens=max_tokens,
                    prompt_sha256=sha,
                    correlation_id=opp.id,
                )
            )
            return parse_files(response.content)
        except (BrainError, ProviderError, CodeBlockError) as exc:
            notes.append(f"{purpose}: no answer ({type(exc).__name__}: {str(exc)[:200]})")
            return None

    def _show(self, rev: str, path: str) -> str:
        return _git(self.repo, "show", f"{rev}:{path}")

    def _handlers(self, opp: Opportunity, rev: str) -> list[tuple[str, str, str]]:
        from unbidden.world.relations import handler_source

        out: list[tuple[str, str, str]] = []
        for code in opp.details.get("code", []):
            if code.get("file"):
                out.append(
                    (
                        code["endpoint"],
                        code["file"],
                        handler_source(self.repo, rev, code["file"], int(code["line"] or 1)),
                    )
                )
        return out

    def _models_file(self, rev: str, table: str) -> str | None:
        for path in _git(self.repo, "ls-tree", "-r", "--name-only", rev).splitlines():
            if path.endswith(".py") and not re.search(r"(^|/)(tests|alembic|migrations|versions)/", path):
                text = self._show(rev, path)
                if re.search(rf"class\s+{re.escape(table)}\s*\(", text, re.IGNORECASE) and "table=True" in text:
                    return path
                if re.search(rf"__tablename__\s*=\s*[\"']{re.escape(table)}[\"']", text):  # SQLAlchemy
                    return path
        return None

    def _schema_file(self, rev: str, table: str) -> tuple[str, bool] | None:
        """Where `table`'s columns are declared: the model that maps it (True), else the Alembic migration that
        creates it (False), for projects whose code reads the database with SQL and keeps no ORM model."""
        if models := self._models_file(rev, table):
            return models, True
        created = re.compile(
            rf"create_table\(\s*[\"']{re.escape(table)}[\"']|CREATE\s+TABLE\s+(IF\s+NOT\s+EXISTS\s+)?[\"`]?"
            rf"{re.escape(table)}[\"`]?\s*\(",
            re.IGNORECASE,
        )
        for path in _git(self.repo, "ls-tree", "-r", "--name-only", rev).splitlines():
            if "/versions/" in path and path.endswith(".py") and created.search(self._show(rev, path)):
                return path, False
        return None

    def _related_models(self, rev: str, models_file: str, table: str, budget: int = 6000) -> str:
        """The classes of the tables `table` references (its foreign keys): a workload has to create those rows
        first, with their own required columns, and they are often in other files."""
        source = self._show(rev, models_file)
        lines = source.splitlines()
        mapped = next(
            (i for i, x in enumerate(lines) if re.search(rf"__tablename__\s*=\s*[\"']{re.escape(table)}[\"']", x)), None
        )
        block = source
        if mapped is not None:
            start = max((i for i in range(mapped) if lines[i].startswith("class ")), default=0)
            end = next((i for i in range(mapped + 1, len(lines)) if lines[i].startswith("class ")), len(lines))
            block = "\n".join(lines[start:end])
        targets = list(dict.fromkeys(re.findall(r"ForeignKey\(\s*[\"'](\w+)\.", block)))
        out: list[str] = []
        for target in targets:
            path = self._models_file(rev, target)
            if path is None:
                continue
            text = self._show(rev, path).splitlines()
            at = next(
                (i for i, x in enumerate(text) if re.search(rf"__tablename__\s*=\s*[\"']{re.escape(target)}[\"']", x)),
                None,
            )
            if at is None:
                continue
            start = max((i for i in range(at) if text[i].startswith("class ")), default=0)
            end = next((i for i in range(at + 1, len(text)) if text[i].startswith("class ")), len(text))
            out.append(f"`{target}` in `{path}`:\n```python\n" + "\n".join(text[start:end])[:2500] + "\n```")
        return "\n\n".join(out)[:budget] or "(none found)"

    def _test_examples(
        self, rev: str, endpoint: str = "", table: str = "", budget: int = 9000, visible: set[str] | None = None
    ) -> str:
        """What a workload needs to fit the repository's own tests, within what one request may carry: every pytest
        fixture the suite defines (name, parameters, file) and the classes they are typed with, then an existing test
        that calls the endpoint (its imports and calls are real), then the fixture files about the table and the
        conftest."""
        tracked = _git(self.repo, "ls-tree", "-r", "--name-only", rev).splitlines()
        tests = [p for p in tracked if p.endswith(".py") and re.search(r"(^|/)tests?/", p)]
        sources = {p: self._show(rev, p) for p in tests}
        blocks: list[str] = []
        calling: list[str] = []  # placed after the fixtures and their types, which matter more and are shorter

        # 1. A test that calls the endpoint, by its path or by a constant holding it (`foods_merge = "/api/..."`).
        path = endpoint.partition(" ")[2]
        literal = re.sub(r"\{[^}]*\}.*$", "", path).rstrip("/") if path else ""
        if literal:
            names = {
                m.group(1)
                for text in sources.values()
                for m in re.finditer(rf"^(\w+)\s*=\s*f?[\"']{re.escape(literal)}/?[\"']", text, re.MULTILINE)
            }
            needles = [literal, *(rf"\b{n}\b" for n in names)]
            callers = [
                p
                for p, text in sources.items()
                if Path(p).name.startswith("test_")
                and any(re.search(n if n != literal else re.escape(n), text) for n in needles)
            ]
            callers.sort(
                key=lambda p: (
                    -len(set(re.split(r"[/_.]", literal.lower())) & set(re.split(r"[/_.]", p.lower()))),
                    len(sources[p]),
                )
            )
            for caller in callers[:1]:
                # How that test passes credentials, quoted back if a workload is refused (401/403).
                self.auth_lines = [
                    line.strip()
                    for line in sources[caller].splitlines()
                    if re.search(r"\b(headers|auth|cookies)\s*=", line)
                ][:3]
                calling.append(
                    f"An existing test that calls `{endpoint}`, `{caller}`:\n```python\n{sources[caller][:3500]}```"
                )

        # 2. Every fixture the suite defines.
        fixtures = [
            f"- `{m.group(2)}({m.group(3).strip()})` in `{p}`"
            for p, text in sources.items()
            if not Path(p).name.startswith("test_")  # a test module's own fixtures are not visible elsewhere
            for m in re.finditer(r"@(?:pytest\.)?fixture[^\n]*\n(?:@[^\n]*\n)*(async\s+)?def\s+(\w+)\(([^)]*)\)", text)
            if visible is None or m.group(2) in visible  # only those visible where the workload runs (stage 10)
        ]
        if fixtures:
            blocks.append(
                "Fixtures the test suite defines (use these; do not invent others):\n" + "\n".join(fixtures[:80])
            )
            # The classes those fixtures are typed with (`unique_user: TestUser`): their attributes are the contract.
            typed = sorted({t for f in fixtures for t in re.findall(r":\s*(?:\w+\.)?([A-Z]\w+)", f)})
            for name in typed[:6]:
                found = next(
                    (
                        (p, m.start())
                        for p, text in sources.items()
                        if (m := re.search(rf"^class {name}\b", text, re.M))
                    ),
                    None,
                )
                if found is not None:
                    path, at = found
                    body = sources[path][at:]
                    end = re.compile(r"^\S", re.M).search(body, body.find("\n") + 1)  # next top-level line
                    definition = body[: end.start()] if end else body
                    blocks.append(f"`{name}` in `{path}`:\n```python\n{definition[:1500]}```")

        blocks += calling

        # 3. Fixture files about the table, then the conftest.
        words = {w.removesuffix("s") for w in re.split(r"[_.]", table.lower()) if len(w) > 2}
        related = [
            p
            for p in sources
            if re.search(r"(fixture|conftest)", Path(p).name)
            and words & {w.removesuffix("s") for w in re.split(r"[/_.]", p.lower())}
        ]
        for extra in [*related[:2], *[p for p in sources if Path(p).name == "conftest.py"][:1]]:
            blocks.append(f"`{extra}`:\n```python\n{sources[extra][:3000]}```")

        text = "\n\n".join(blocks)
        return text[:budget] if text else "(no test helpers found)"

    # Measurement ----------------------------------------------------------------------------------------

    def _sessions(
        self,
        measure: Callable[[dict[str, str]], tuple[dict[str, Any] | None, str]],
        candidate: dict[str, str],
        seed: str,
        per_arm: int = SESSIONS_PER_ARM,
        arms: tuple[str, str] = ("base", "candidate"),
    ) -> tuple[list[dict[str, Any]] | None, str]:
        """Sessions alternating between two arms, which goes first drawn from `seed` (a rerun repeats the order).
        Every session is one sandbox run with a fresh database, the same image, data and limits: what one session
        changes cannot reach the next. `arms` may name two sets of base sessions (the A/A control)."""
        import random as _random

        first = _random.Random(seed).choice(list(arms))
        second = arms[1] if first == arms[0] else arms[0]
        out: list[dict[str, Any]] = []
        for position, arm in enumerate([first, second] * per_arm):
            record, error = measure(candidate if arm == "candidate" else {})
            if record is None:
                return None, f"{arm} session {position + 1}: {error}"
            out.append({"arm": arm, "position": position, **record})
        return out, ""

    def _measure(
        self,
        rev: str,
        files: dict[str, str],
        plan: TestPlan,
        test_dir: str,
        relation: tuple[str, str],
        index: tuple[str, str] | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        """In-process: the workload run as a test of the repository's CI test command, selected by name, beside a
        fresh database; then what the engine says it did: index scans on `index`, the statements that read
        `relation` (pg_stat_statements), the rows inserted."""
        self.scans = None
        image = self.images["python"]
        work = snapshot(self.repo, rev)
        try:
            driver = DRIVER
            if self.marker is not None:
                driver = async_driver(files.get(f"{LAB_DIR}/workload.py", ""), self.marker) or DRIVER
            for path, content in {**files, f"{test_dir}/{DRIVER_TEST}.py": driver}.items():
                target = work / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)
                target.chmod(0o666)
            (work / LAB_DIR).chmod(0o777)
            link_dependencies(work, image)
            env = {**plan.env, "PYTEST_ADDOPTS": f"-k {DRIVER_TEST} -p no:cacheprovider"}
            statements: list[dict[str, Any]] | None = None
            inserted: dict[str, int] | None = None
            with data_services(list(plan.services), statements=True) as sidecars:
                spec = sandbox_spec(
                    image,
                    list(serial(plan.argv)),
                    public_env=env,
                    timeout_s=900,
                    network=sidecars.network if sidecars else "none",
                )
                result = self.runner.run(spec, work)
                if index is not None and sidecars is not None:
                    self.scans = index_scans(sidecars, list(plan.services), *index)
                psql = postgres_of(sidecars, list(plan.services))
                if psql is not None:
                    try:
                        psql("CREATE EXTENSION IF NOT EXISTS pg_stat_statements;")
                        statements = statements_using(psql, *relation, SAMPLES)
                        inserted = _inserted(psql, [relation[0], *self.parents])
                    except RuntimeError:
                        statements = None
            out = work / LAB_DIR / "result.json"
            if out.exists():
                data = json.loads(out.read_text())
                self.engine = data.get("engine") or self.engine
                samples = [float(x) for x in data["latencies_ms"]]
                return {"samples_ms": samples, "median_ms": statistics.median(samples), "index_scans": self.scans,
                        "digests": data.get("digests") or [], "sample": data.get("sample") or "",
                        "statements": statements, "inserted": inserted}, ""  # fmt: skip
            return None, failure_excerpt(result.stdout + result.stderr)
        finally:
            discard(work)

    def _served(
        self, rev: str, files: dict[str, str], recipe: ServerRecipe, request: dict[str, Any], seed: Callable[..., Any],
        index: tuple[str, str] | None,
    ) -> tuple[dict[str, Any] | None, str]:  # fmt: skip
        """Served: the application started as the project starts it, beside a fresh database (`served.py`)."""
        image = self.images["python"]
        work = snapshot(self.repo, rev)
        try:
            for path, content in files.items():
                (work / path).parent.mkdir(parents=True, exist_ok=True)
                (work / path).write_text(content)
            link_dependencies(work, image)
            session = run_session(self.runner, image, work, recipe, request, seed, warmup=WARMUP, samples=SAMPLES,
                                  index=index, scans=index_scans)  # fmt: skip
            self.engine = "postgresql"
            self.last_session = session
            if session.samples_ms is None:
                return None, session.error
            return {"samples_ms": session.samples_ms, "median_ms": statistics.median(session.samples_ms),
                    "index_scans": session.scans, "digests": session.digests, "sample": session.sample,
                    "statements": session.statements, "statuses": session.statuses, "data": session.data,
                    "data_ok": session.data_ok}, ""  # fmt: skip
        finally:
            discard(work)

    def _engine_caveat(self) -> list[str]:
        """A speed-up measured on one database engine may not hold on another: planners differ (on mealie, SQLite
        runs a NOT EXISTS once per row where Postgres hashes it in one pass)."""
        from unbidden.contracts.world import WorldModel

        world = self.store.get("world", "world", WorldModel)
        running = sorted(
            {
                str(r.attributes.get("engine"))
                for r in (world.of_kind("database") if world else [])
                if r.attributes.get("engine")
            }
        )
        measured = {"postgresql": "postgres", "sqlite": "sqlite", "mysql": "mysql"}.get(self.engine or "", self.engine)
        uses = ", ".join(running) or "an unknown engine"
        if not measured:
            return [f"the database engine of the measurement is unknown; the running system uses {uses}"]
        if running and measured not in running:
            return [
                f"measured on {measured}; the running system uses {uses}: observe the effect there, do not assume it"
            ]
        return [f"measured on {measured}, the running system's engine"]

    def _keep(self, opp: Opportunity, name: str, code: str, output: str) -> None:
        """Failed attempts are evidence too: kept next to the experiments for `unbidden why`."""
        if self.store.path is None:
            return
        folder = self.store.path.parent / "artifacts" / opp.id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{name}.py").write_text(code)
        (folder / f"{name}.log").write_text(output)

    def _findings(self, rev: str, files: dict[str, str]) -> Counter[str]:
        """Findings of every check the repository uses, as a multiset of 'tool rule path: message'."""
        image = self.images["python"]
        work = snapshot(self.repo, rev)
        try:
            for path, content in files.items():
                (work / path).parent.mkdir(parents=True, exist_ok=True)
                (work / path).write_text(content)
            link_dependencies(work, image)
            found: Counter[str] = Counter()
            for tool in tools_for(self.stack):
                if tool.language != "python":
                    continue
                result = self.runner.run(sandbox_spec(image, list(tool.argv), cwd=tool.cwd), work)
                for f in tool.report(result, list(tool.argv)).findings:
                    found[f"{f.tool} {f.rule} {f.path}: {f.message}"] += 1
            return found
        finally:
            discard(work)

    # The experiment -------------------------------------------------------------------------------------

    def _added(self, rev: str, files: dict[str, str], before: Counter[str]) -> Counter[str]:
        """Findings the change adds. In a file the change creates, a rule its directory's existing files already break
        is the project's convention, not the change's doing (stage 10: Spoolman lints with every rule, its migrations
        carry no copyright notice, and so would any new one)."""
        added = self._findings(rev, files) - before
        broken = {(k.split(" ", 2)[1], str(Path(k.split(" ", 2)[2].split(":", 1)[0]).parent)) for k in before}
        existing = set(_git(self.repo, "ls-tree", "-r", "--name-only", rev).splitlines())
        for key in list(added):
            _, rule, rest = key.split(" ", 2)
            path = rest.split(":", 1)[0]
            if path not in existing and path in files and (rule, str(Path(path).parent)) in broken:
                del added[key]
        return added

    def _parents(self, rev: str, models_file: str, table: str) -> list[str]:
        """The tables `table` references (its foreign keys), read from its model or migration."""
        source = self._show(rev, models_file)
        return list(dict.fromkeys(re.findall(r"ForeignKey\(\s*[\"'](\w+)\.", source)))[:8]

    def _reference(self, rev: str, models_file: str, column: str) -> str | None:
        """The table `column` references, from the line that declares it (`ForeignKey("filament.id")`)."""
        for line in self._show(rev, models_file).splitlines():
            if re.match(rf"\s*{re.escape(column)}\s*[:=]", line) and (
                m := re.search(r"ForeignKey\(\s*[\"'](\w+)\.", line)
            ):
                return m.group(1)
        return None

    async def _candidate(
        self, opp: Opportunity, rev: str, table: str, column: str, head: tuple[str, str, str], models_file: str,
        has_model: bool, handlers: list[tuple[str, str, str]], result: PerfResult,
    ) -> Candidate | None:  # fmt: skip
        """The schema change: written from the finding by rule when it can be, else by the model; either way held to
        the repository's own checks (a speed-up may not bring new findings with it)."""
        cand_prompt = load_prompt("perf_candidate")
        migrations_dir, head_rev, head_file = head
        content = cand_prompt.render(
            problem=opp.summary,
            migrations_dir=migrations_dir,
            head=head_rev,
            head_file=head_file,
            head_example=self._show(rev, head_file)[:4000],
            models_file=models_file,
            models=self._show(rev, models_file)[:8000],
            handlers="\n\n".join(f"`{e}` in `{f}`:\n```python\n{c}```" for e, f, c in handlers[:4]),
        )
        before_findings = self._findings(rev, {})
        candidate_files: dict[str, str] | None = None
        origin = ""
        if opp.details.get("check") == "unindexed_foreign_key" and column:
            candidate_files = index_candidate(
                lambda path: self._show(rev, path), table, column, models_file, head, model=has_model
            )
            added = self._added(rev, candidate_files, before_findings) if candidate_files else None
            if added:
                listed = "; ".join(sorted(added.elements())[:3])
                result.notes.append(f"the written index change added findings ({listed}); asking the model instead")
                candidate_files = None
            elif candidate_files:
                origin = "rule"  # written by Unbidden from the finding, no model involved
                self.progress(f"candidate: index on {table}.{column}, written from the finding")
        for attempt in range(0 if candidate_files else 2):
            self.progress(f"asking the local model for the schema change (attempt {attempt + 1})")
            candidate_files = await self._ask_files(
                "lab.perf_candidate", content, opp, cand_prompt.sha256, 4000, result.notes
            )
            if not candidate_files:
                continue
            new = self._added(rev, candidate_files, before_findings)
            if not new:
                break
            listed = "\n".join(f"- {f}" for f in sorted(new.elements())[:10])
            result.notes.append(f"candidate attempt {attempt + 1} added {sum(new.values())} finding(s)")
            content += (
                f"\n\nYour previous change added findings from this repository's own checks:\n{listed}\nAvoid them."
            )
            candidate_files = None
        if not candidate_files:
            result.notes.append("the local model gave no schema change that keeps the repository's checks clean")
            return None
        base_dir = snapshot(self.repo, rev)
        candidate = Candidate(
            origin or self.brain.author("lab.perf_candidate"), candidate_files, unified_patch(base_dir, candidate_files)
        )
        discard(base_dir)
        return candidate

    def _visible_fixtures(self, rev: str, test_dir: str) -> set[str]:
        """Fixtures a test placed in `test_dir` can use: those of the conftest files in it and above it, and of the
        modules they load as plugins (stage 10: Spoolman's workloads asked for `random_filament`, a fixture of
        `tests_integration/`, invisible from `tests/`)."""
        tracked = _git(self.repo, "ls-tree", "-r", "--name-only", rev).splitlines()
        parts = Path(test_dir).parts
        ancestors = {str(Path(*parts[:i])) if i else "." for i in range(len(parts) + 1)}
        conftests = [p for p in tracked if Path(p).name == "conftest.py" and str(Path(p).parent) in ancestors]
        texts = {p: self._show(rev, p) for p in conftests}

        def module_of(path: str) -> str:
            # A package's __init__.py is the package itself (mealie: `from tests.fixtures import *`).
            return path.removesuffix(".py").removesuffix("/__init__").replace("/", ".")

        modules = {module_of(p): p for p in tracked if p.endswith(".py")}
        pending = list(texts)
        while pending:  # what they load, and what that loads in turn (a package re-exporting its modules)
            path = pending.pop()
            text = texts[path]
            package = module_of(path) if path.endswith("__init__.py") else module_of(path).rpartition(".")[0]
            relative = {f"{package}.{m}" if package else m for m in re.findall(r"from\s+\.(\w[\w.]*)\s+import", text)}
            for module, file in modules.items():
                if file in texts:
                    continue
                # Without its top package (a conftest's `fixtures.x` for `tests.fixtures.x`) only from a conftest:
                # followed further, so short a name would match nearly every module.
                loose = path in conftests and module.split(".", 1)[-1] in text
                if module in relative or module in text or loose:
                    texts[file] = self._show(rev, file)
                    pending.append(file)
        names = {
            m.group(2)
            for text in texts.values()
            for m in re.finditer(
                r"@(?:pytest(?:_asyncio)?\.)?fixture[^\n]*\n(?:@[^\n]*\n)*(async\s+)?def\s+(\w+)\(", text
            )
        }
        return names | BUILTIN_FIXTURES

    async def _prepare_in_process(
        self, opp: Opportunity, rev: str, plan: TestPlan, test_dir: str, cwd: str, endpoint: str,
        handler: tuple[str, str, str], models_file: str, has_model: bool, relation: tuple[str, str],
        result: PerfResult,
    ) -> tuple[Callable[[dict[str, str]], tuple[dict[str, Any] | None, str]], str, dict[str, Any], dict[str, Any],
               dict[str, Any]] | None:  # fmt: skip
        """A workload written as one more test of the project's suite, validated at the base."""
        table = relation[0]
        index = (relation[0], relation[1]) if opp.details.get("check") == "unindexed_foreign_key" else None
        visible = self._visible_fixtures(rev, test_dir)
        wl_prompt = load_prompt("perf_workload")
        feedback = ""
        for attempt in range(self.repairs + 1):
            self.progress(f"writing the workload (attempt {attempt + 1})")
            workload = await self._ask_files(
                "lab.workload",
                wl_prompt.render(
                    framework="FastAPI",
                    async_rule=_ASYNC_RULE if self.marker else "",
                    endpoint=endpoint,
                    rows=str(SEED_ROWS),
                    owners=str(SEED_OWNERS),
                    table=table,
                    cwd=f"/work/{cwd}",
                    feedback="",
                    handler_file=handler[1],
                    handler=handler[2],
                    models_file=models_file,
                    models=self._show(rev, models_file)[:8000],
                    schema_label="The data models" if has_model else "The migration that creates the tables",
                    insert_rule=_ORM_INSERT if has_model else _SQL_INSERT,
                    related_models=self._related_models(rev, models_file, table),
                    calls=str(WARMUP + SAMPLES),
                    test_examples=self._test_examples(rev, endpoint, table, visible=visible),
                ),
                opp,
                wl_prompt.sha256,
                3000,
                result.notes,
                lab_output=feedback,
            )
            workload = {k: v for k, v in (workload or {}).items() if k == f"{LAB_DIR}/workload.py"}
            if not workload:
                feedback = "Your previous answer had no `# file: .unbidden-lab/workload.py` block."
                continue
            text = workload[f"{LAB_DIR}/workload.py"]
            wrong = signature_problems(text, visible)
            if wrong:
                # Refused before running: pytest would take these parameters for fixtures it does not have.
                feedback = f"Your previous workload cannot run: {wrong}. Fix it."
                result.notes.append(f"workload attempt {attempt + 1} refused before running: {wrong[:200]}")
                self._keep(opp, f"workload-attempt-{attempt + 1}", text, f"refused before running: {wrong}")
                continue
            self.progress("validating the workload at the base")
            record, error = self._measure(rev, workload, plan, test_dir, relation, index)
            if record is None:
                feedback = f"Your previous workload failed when run. The end of its output:\n```\n{error}\n```\nFix it."
                if re.search(r"HTTP 40[13]\b|assert 40[13] == 200", error):
                    feedback += (
                        "\nThe request was not authenticated or not allowed. Pass credentials exactly as the existing"
                        " test shown below does (the same fixture attribute, the same argument), without wrapping them"
                        " again; if the endpoint needs a permission, use the fixture that has it."
                    )
                    if self.auth_lines:
                        feedback += " That test does it like this:\n" + "\n".join(f"    {x}" for x in self.auth_lines)
                last_line = next((ln for ln in error.splitlines() if ln.startswith("E ") or "Error" in ln), "no output")
                result.notes.append(f"workload attempt {attempt + 1} failed: {last_line[:200]}")
                self._keep(opp, f"workload-attempt-{attempt + 1}", text, error)
                continue
            ok, problems, passed = validate_in_process(record, relation, endpoint.startswith("GET "))
            if not ok and _only_unused(problems):
                seen = "; ".join(str(s["query"])[:200] for s in (record.get("statements") or [])[:2])
                self.unused.append(f"{endpoint}: {seen}")
            if not ok:
                feedback = (
                    "Your previous workload ran, but it does not measure what it must:\n- "
                    + "\n- ".join(problems)
                    + "\nFix it."
                )
                result.notes.append(f"workload attempt {attempt + 1} not valid: {'; '.join(problems)[:300]}")
                self._keep(opp, f"workload-attempt-{attempt + 1}", text, "not valid:\n" + "\n".join(problems))
                continue
            method, _, path = endpoint.partition(" ")
            operation = {
                "method": method,
                "path": path,
                "source": f"{handler[1]} (the endpoint's handler, from the map)",
                "request": "a test of the project's suite written by a model, run by a fixed driver",
            }
            data = {
                "tables": {table: SEED_ROWS},
                "owners": SEED_OWNERS,
                "written_by": "the workload (model-written); the rows the engine counted are in the validation",
            }
            validation = {
                "attempt": attempt + 1,
                "passed": passed,
                "statements": record.get("statements"),
                "inserted": record.get("inserted"),
            }

            def measure(files: dict[str, str], wl: dict[str, str] = workload) -> tuple[dict[str, Any] | None, str]:
                return self._measure(rev, {**files, **wl}, plan, test_dir, relation, index)

            return measure, text, operation, data, validation
        return None

    async def _choose_request(
        self, opp: Opportunity, relation: tuple[str, str], parent: str, handlers: list[tuple[str, str, str]],
        feedback: str, result: PerfResult, models: str = "",
    ) -> dict[str, Any] | None:  # fmt: skip
        prompt = load_prompt("perf_request")
        table, column = relation
        content = prompt.render(
            table=table, column=column, parent=parent, rows=str(SEED_ROWS), owners=str(SEED_OWNERS),
            parent_note=f", which references `{parent}`" if parent else "",
            endpoints="\n".join(f"- {e}" for e in opp.details.get("endpoints", [])),
            handlers="\n\n".join(f"`{e}` in `{f}`:\n```python\n{c}```" for e, f, c in handlers[:4]),
            calls=str(WARMUP + SAMPLES), feedback="", models=models[:7000],
        )  # fmt: skip
        schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                "method": {"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"]},
                "path": {"type": "string"},
                "query": {"type": "object", "additionalProperties": {"type": "string"}},
                "body": {},
                "values_sql": {"type": "string"},
                "setup_sql": {"type": "string"},
                "why": {"type": "string"},
            },
            "required": ["method", "path", "query", "values_sql", "why"],
        }
        messages = [Message(role="user", content=content, source="repo")]
        if feedback:
            messages.append(Message(role="user", content=mask_personal(redact_text(feedback)), source="synthetic"))
        try:
            value, _ = await self.brain.complete_json(LLMRequest(
                purpose="lab.perf_request", tier=Tier.LOCAL, messages=messages, response_schema=schema,
                max_tokens=800, prompt_sha256=prompt.sha256, correlation_id=opp.id,
            ))  # fmt: skip
        except (BrainError, ProviderError) as exc:
            result.notes.append(f"lab.perf_request: no answer ({type(exc).__name__}: {str(exc)[:200]})")
            return None
        sql = str(value.get("values_sql", "")).strip().rstrip(";")
        if not re.match(r"(?is)^\s*(select|with)\b", sql) or ";" in sql:
            result.notes.append(f"request refused: values_sql is not one SELECT ({sql[:120]!r})")
            return None
        setup = str(value.get("setup_sql") or "").strip()
        statements = [s.strip() for s in setup.split(";") if s.strip()]
        if any(
            not re.match(r"(?is)^update\s+\w+\s+set\b", s)
            or re.search(r"(?i)\b(drop|alter|create|truncate|insert|delete|grant|copy|pg_\w+\()", s)
            for s in statements
        ):
            result.notes.append(f"request refused: setup_sql may only UPDATE seeded rows ({setup[:120]!r})")
            return None
        served = {e.partition(" ")[2] for e in opp.details.get("endpoints", [])}
        path = str(value["path"])
        template = re.sub(r"\{value\}", "{x}", path)
        if not any(re.sub(r"\{[^}]+\}", "{x}", s) == template for s in served):
            result.notes.append(f"request refused: {path} is not one of the endpoints that use the relation")
            return None
        return {
            "method": value["method"],
            "path": path,
            "query": dict(value.get("query") or {}),
            "body": value.get("body"),
            "values_sql": f"BEGIN READ ONLY; {sql}; COMMIT;",
            "why": value.get("why", ""),
            "setup_sql": "; ".join(statements) + ";" if statements else "",
            "table": table,
            "column": column,
        }

    async def _prepare_served(
        self, opp: Opportunity, rev: str, recipe: ServerRecipe, relation: tuple[str, str],
        handlers: list[tuple[str, str, str]], result: PerfResult,
    ) -> tuple[Callable[[dict[str, str]], tuple[dict[str, Any] | None, str]], str, dict[str, Any], dict[str, Any],
               dict[str, Any]] | None:  # fmt: skip
        """The application as the project runs it; the database seeded from its catalog; a request chosen by a model
        among the endpoints that use the relation and validated at the base by the engine's own statistics."""
        table, column = relation
        index = relation if opp.details.get("check") == "unindexed_foreign_key" else None
        models_file = self._schema_file(rev, table)
        parent = (self._reference(rev, models_file[0], column) if models_file else None) or ""
        plans: list[SeedPlan] = []

        def seed(psql: Psql) -> SeedPlan:
            paths = [e.partition(" ")[2] for e in opp.details.get("endpoints", [])]
            plan = plan_seed(psql, table, column, SEED_ROWS, SEED_OWNERS, paths=paths)
            plans.append(plan)
            return plan

        feedback = ""
        for attempt in range(self.repairs + 1):
            self.progress(f"choosing the request (attempt {attempt + 1})")
            request = await self._choose_request(opp, relation, parent, handlers, feedback, result,
                                                 self._show(rev, models_file[0]) if models_file else "")  # fmt: skip
            if request is None:
                feedback = "Your previous answer was refused: " + (result.notes[-1] if result.notes else "")
                continue
            self.progress("validating the request at the base, against the application as the project runs it")
            self._served(rev, {}, recipe, request, seed, index)
            session = self.last_session
            assert session is not None
            if session.error.startswith(("the application did not start", "seeding the database failed")):
                # Not the request's fault: nothing a model can repair. Said precisely, as the environment's.
                result.notes.append(f"workload: {session.error[:600]}")
                self.prep_block = ("environment_ready" if session.error.startswith("the application") else
                                   "workload_valid", session.error[:600])  # fmt: skip
                return None
            ok, problems = validate(session, table, column, SAMPLES, reads=request["method"] == "GET")
            self._keep(opp, f"request-attempt-{attempt + 1}", json.dumps(request, indent=1),
                       "valid" if ok else "not valid:\n" + "\n".join(problems))  # fmt: skip
            if not ok and _only_unused(problems):
                self.unused.append(f"{request['method']} {request['path']}: " + "; ".join(
                    str(s["query"])[:200] for s in session.statements[:2]))  # fmt: skip
            if not ok:
                feedback = ("Your previous request ran, but it does not measure what it must:\n- "
                            + "\n- ".join(problems) + "\nChoose again.")  # fmt: skip
                result.notes.append(f"request attempt {attempt + 1} not valid: {'; '.join(problems)[:300]}")
                continue
            operation = {"method": request["method"], "path": request["path"], "query": request["query"],
                         "body": request["body"], "values": request["values_sql"], "why": request["why"],
                         "data_adapted_by_model": request.get("setup_sql") or "",
                         "source": "chosen by a model among the endpoints the map relates to the table; checked by the "
                                   "engine's statement statistics"}  # fmt: skip
            data = describe(plans[-1]) if plans else {}
            validation = {"attempt": attempt + 1, "passed": [
                "the application started as the project starts it (" + recipe.command[:120] + ")",
                f"every call succeeded ({len(session.statuses)} calls)",
                f"the engine ran a statement reading {table} by {column} on every call",
                f"data: {session.data}"], "statements": session.statements[:3]}  # fmt: skip
            frozen = dict(request)

            def measure(files: dict[str, str], req: dict[str, Any] = frozen) -> tuple[dict[str, Any] | None, str]:
                return self._served(rev, files, recipe, req, seed, index)

            return measure, json.dumps(frozen, sort_keys=True), operation, data, validation
        return None

    async def run(self, opp: Opportunity) -> PerfResult:
        result = PerfResult()
        rev: str = opp.details["rev"]
        table, endpoints = opp.details["table"], opp.details["endpoints"]
        column = str(opp.details.get("column", ""))
        readiness: dict[str, dict[str, Any]] = {}

        def ready(state: str, ok: bool, why: str) -> None:
            readiness[state] = {"ok": ok, "why": why[:400]}
            opp.details = {**opp.details, "readiness": dict(readiness)}

        def blocked(state: str, why: str) -> PerfResult:
            """A preparation that failed: not an absent opportunity, not a negative result (stage 10)."""
            ready(state, False, why)
            result.blocked = f"cannot measure: {why}"
            result.notes.append(result.blocked)
            opp.updated_at = utc_now()
            self.store.put("opportunities", opp)
            return result

        plan = test_plan(self.repo, rev, self.stack, "python")
        ci = ci_test_plan(self.repo, rev, "python")
        head = alembic_head(self.repo, rev)
        self.marker = async_suite(
            lambda path: self._show(rev, path), _git(self.repo, "ls-tree", "-r", "--name-only", rev).splitlines()
        )
        schema = self._schema_file(rev, table)
        models_file, has_model = schema if schema else (None, False)
        handlers = self._handlers(opp, rev)
        missing = [
            what
            for what, have in (
                # The project's test command, from its CI job or, without one, the same fallback the base checks
                # use (stage 9 evaluation, Spoolman: its CI runs no pytest step, the base checks ran 278 tests, and
                # every experiment was blocked for want of a CI job).
                ("a way to run the project's tests", plan is not None),
                ("a single Alembic head", head is not None),
                (f"the schema of table {table} (a model, or the migration that creates it)", models_file is not None),
                ("the handlers of the endpoints that read it", bool(handlers)),
            )
            if not have
        ]
        enforcing = plan is not None and any(
            re.match(r"(.*/)?(postgres|postgis|mysql|mariadb)\b", s.image or "") for s in plan.services
        )
        if missing:
            return blocked("environment_ready", "no " + ", no ".join(missing))
        assert plan is not None and head is not None and models_file is not None
        ready("environment_ready", True, f"dependency image built; tests run by {plan.source}; migrations at {head[0]}")
        checks = self.store.get_value("baseline_checks") or {}
        if checks.get("rev") == rev and checks.get("status") in ("passed", "failed") and checks.get("collected"):
            ready("checks_reproduced", True, f"{checks['status']} at the base, {checks['collected']} collected "
                                             f"({checks.get('scope') or plan.scope})")  # fmt: skip
        else:
            ready("checks_reproduced", False, "not recorded at this commit (the lab's own test runs decide)")
        cwd = ci.steps[-1].cwd if ci is not None and ci.steps else "."
        test_dir = self.stack.python.test_paths[0] if self.stack.python and self.stack.python.test_paths else "tests"
        inv = inventory(self.repo, rev, [test_dir])
        mode = inv.mode
        if mode is None:
            return blocked("environment_ready", "the project's API tests run neither in-process nor against a "
                                                f"server it says how to start ({inv.why_not_served})")  # fmt: skip
        if opp.details.get("cost_path") == "parent_delete" and not (enforcing or mode == "served"):
            # The cost is the database's own foreign-key check; whether the test database makes it (SQLite only
            # with `PRAGMA foreign_keys`) is not something the lab can tell. PostgreSQL always enforces them.
            return blocked("environment_ready", "no test database known to enforce foreign keys")
        preparation = [e.as_dict() for e in inv.evidence]
        list_endpoint = next((e for e in endpoints if e.startswith("GET ") and "{" not in e), endpoints[0])
        handler = next((h for h in handlers if h[0] == list_endpoint), handlers[0])
        tables = self._parents(rev, models_file, table)
        self.parents = tables

        # Candidate, held to the repository's own checks: a speed-up may not bring new findings with it.
        candidate = await self._candidate(opp, rev, table, column, head, models_file, has_model, handlers, result)
        if candidate is None:
            # Nothing was measured: no change could be written that keeps the project's checks clean. A block with its
            # notes, not an experiment that found no fix (stage 10, Spoolman: counted twice as failures, then declined).
            return blocked(
                "experiment_executed",
                "no candidate change keeps the project's own checks clean ("
                + "; ".join(n for n in result.notes if "candidate" in n or "finding" in n)[:300]
                + ")",
            )
        index = (table, column) if opp.details.get("check") == "unindexed_foreign_key" and column else None
        relation = (table, column) if column else (table, "id")

        # The workload, validated at the base before any comparison, repaired a bounded number of times.
        if mode == "served":
            assert inv.server is not None
            prepared = await self._prepare_served(opp, rev, inv.server, relation, handlers, result)
        else:
            prepared = await self._prepare_in_process(opp, rev, plan, test_dir, cwd, list_endpoint, handler,
                                                      models_file, has_model, relation, result)  # fmt: skip
        if prepared is None and self.prep_block is not None:
            return blocked(*self.prep_block)
        if prepared is None and len(self.unused) >= 2:
            # Requests ran without help, on the data, and answered; the engine shows none looks the table up by the
            # column. Not a preparation that failed: the claimed use is not there (verified absence, stage 10).
            why = (f"{len(self.unused)} requests to the endpoints that use {relation[0]}.{relation[1]} ran and "
                   f"answered, and the engine shows none of them looks {relation[0]} up by {relation[1]} ("
                   + " | ".join(self.unused[:2])[:600] + ")")  # fmt: skip
            ready("workload_valid", False, why)
            result.absent = why
            result.notes.append(f"no opportunity here: {why}")
            opp.updated_at = utc_now()
            self.store.put("opportunities", opp)
            return result
        if prepared is None:
            last = next((n for n in reversed(result.notes) if n.startswith(("workload", "lab.", "request"))), "")
            return blocked("workload_valid", f"no workload was valid at the base after {self.repairs + 1} attempts "
                                             f"({last})")  # fmt: skip
        measure, workload_text, operation, data, validation = prepared
        ready("workload_valid", True, "; ".join(validation["passed"]))

        # The spec, fixed before the first comparison.
        workload_sha = hashlib.sha256(workload_text.encode()).hexdigest()
        reads = operation.get("method", "GET") == "GET"
        scope = (f"{operation.get('method')} {operation.get('path')} on {data.get('tables') or data}, "
                 f"{'PostgreSQL' if mode == 'served' or enforcing else 'the test database'} in a sandbox, "
                 f"{'the application as the project runs it' if mode == 'served' else 'inside the test suite'}; "
                 "not a claim about other endpoints, other data or production")  # fmt: skip
        spec = ExperimentSpec(
            opportunity_id=opp.id, base_sha=rev, mode=mode, operation=operation, data=data,
            functional_checks=["every warm-up and measured call succeeds",
                               "the response carries data" if reads else "the call acts on its own target",
                               "the same responses on both sides (canonical JSON digests)",
                               f"the engine ran a statement reading {relation[0]} by {relation[1]} on every call"],
            metric="wall-clock time of one request, ms, median per session", warmup=WARMUP, samples=SAMPLES,
            sessions_per_arm=SESSIONS_PER_ARM, order_seed=opp.id, threshold=MIN_EFFECT,
            criteria=PROMOTION_CRITERIA, scope=scope, workload_sha256=workload_sha, preparation=preparation,
        )  # fmt: skip
        self.store.put("experiment_specs", spec)

        self.progress(f"measuring {SESSIONS_PER_ARM} sessions per side, alternating")
        sessions, error = self._sessions(measure, candidate.files, opp.id)
        if sessions is None:
            ready("experiment_executed", False, f"the candidate broke the workload: {error[-300:]}")
            result.notes.append(f"the candidate broke the workload: {error[-300:]}")
            opp.updated_at = utc_now()
            self.store.put("opportunities", opp)
            return result
        ready("experiment_executed", True, f"{len(sessions)} sessions")
        base = [s["median_ms"] for s in sessions if s["arm"] == "base"]
        cand = [s["median_ms"] for s in sessions if s["arm"] == "candidate"]
        mechanism, mechanism_note = _mechanism(sessions, index)
        functional, functional_note = _same(sessions)
        first = judge_sessions(base, cand, mechanism=mechanism, mechanism_note=mechanism_note)
        control: list[dict[str, Any]] = []
        confirmation: list[dict[str, Any]] = []
        family = 1
        if first.improved and functional:
            self.progress("A/A control: base against base")
            control = self._sessions(measure, {}, f"{opp.id}:control", CONTROL_SESSIONS, ("base-a", "base-b"))[0] or []
            confirmed = list(self.store.get_value(f"confirmations:{rev}") or [])
            family = len(dict.fromkeys([*confirmed, opp.id]))
            self.store.set_value(f"confirmations:{rev}", list(dict.fromkeys([*confirmed, opp.id])))
            per_arm = SESSIONS_PER_ARM if family <= 3 else SESSIONS_PER_ARM + 1
            self.progress(f"confirming in {per_arm} new sessions per side ({family} candidate(s) at this commit)")
            confirmation = self._sessions(measure, candidate.files, f"{opp.id}:confirm", per_arm)[0] or []
        aa = ([s["median_ms"] for s in control if s["arm"] == "base-a"],
              [s["median_ms"] for s in control if s["arm"] == "base-b"]) if control else None  # fmt: skip
        again = (
            (
                [s["median_ms"] for s in confirmation if s["arm"] == "base"],
                [s["median_ms"] for s in confirmation if s["arm"] == "candidate"],
            )
            if confirmation
            else None
        )
        promotion = judge_promotion(
            (base, cand), mechanism=mechanism, mechanism_note=mechanism_note, functional_same=functional,
            functional_note=functional_note, control=aa, confirmation=again,
            confirmation_mechanism=_mechanism(confirmation, index)[0] if confirmation else None, family=family,
        )  # fmt: skip

        self.progress("running the CI test job on both sides")
        image = self.images["python"]
        sides = []
        for files in ({}, candidate.files):
            work = snapshot(self.repo, rev)
            for path, content in files.items():
                (work / path).parent.mkdir(parents=True, exist_ok=True)
                (work / path).write_text(content)
            link_dependencies(work, image)
            sides.append(run_suite(self.runner, work, image, plan, rounds=3))
            discard(work)
        tests, test_notes = classify_tests(sides[0], sides[1])
        improved = promotion.improved and tests is not TestOutcome.REGRESSION
        level = level_for(improved, tests, suite_ran=True)
        evaluable = promotion.outcome != "inconclusive" or bool(control or confirmation)
        ready("result_evaluable", evaluable, promotion.outcome)
        experiment = Experiment(
            opportunity_id=opp.id,
            base_sha=rev,
            candidate_patch_sha256=candidate.sha256,
            rounds=3,
            baseline_tests=sides[0],
            candidate_tests=sides[1],
            samples_before_ms=[x for s in sessions if s["arm"] == "base" for x in s["samples_ms"]],
            samples_after_ms=[x for s in sessions if s["arm"] == "candidate" for x in s["samples_ms"]],
            sessions=sessions,
            workload_sha256=workload_sha,
            provenance=provenance(self.brain, list(self.images.values()), engine=self.engine),
            spec_id=spec.id,
            validation=validation,
            control=control,
            confirmation=confirmation,
        )
        outcome = "regression" if tests is TestOutcome.REGRESSION and promotion.primary.improved else promotion.outcome
        verdict = Verdict(
            experiment_id=experiment.id,
            improved=improved,
            evidence_level=level,
            criteria=PROMOTION_CRITERIA,
            tests=tests,
            reasons=[
                f"{operation.get('method')} {operation.get('path')}: {promotion.reasons[0]}",
                *promotion.reasons[1:],
                *(n for n in test_notes if tests is TestOutcome.REGRESSION),
            ],
            outcome=outcome,
            caveats=[
                f"{data.get('tables') or data}, measured in a sandbox; production effect not yet observed",
                *self._engine_caveat(),
                *(n for n in test_notes if tests is not TestOutcome.REGRESSION),
                f"the project's tests on both sides: {plan.scope}" + (" (part of the suite)" if plan.partial else ""),
            ],
            scope=scope,
            spec_id=spec.id,
        )
        self.store.put("experiments", experiment)
        if self.store.path is not None:
            artifacts = self.store.path.parent / "artifacts"
            artifacts.mkdir(parents=True, exist_ok=True)
            (artifacts / f"{experiment.id}.patch").write_text(candidate.patch)
            (artifacts / f"{experiment.id}.workload.py").write_text(workload_text)
        self.store.append_event(
            Event(
                type=EventType.VERDICT_RECORDED,
                actor=ACTOR,
                entity_id=experiment.id,
                correlation_id=opp.id,
                payload={
                    "improved": improved,
                    "level": int(level),
                    "outcome": verdict.outcome,
                    "p_value": promotion.primary.p_faster,
                    "median_before_ms": promotion.primary.median_before,
                    "median_after_ms": promotion.primary.median_after,
                    "effect": promotion.primary.effect,
                    "tests": tests.value,
                    "spec": spec.id,
                },
            )
        )
        result.experiment, result.verdict, result.candidate = experiment, verdict, candidate
        if improved:
            opp.evidence_level = max(opp.evidence_level, level)
            opp.status = OpportunityStatus.EXPERIMENTING
            opp.details = {
                **opp.details,
                "experiment_id": experiment.id,
                "verdict": verdict.model_dump(mode="json"),
                "candidate": {"origin": candidate.origin, "files": candidate.files},
            }
            opp.evidence = [*opp.evidence, EvidenceRef(kind="experiment", locator=experiment.id)]
        else:
            opp.details = {**opp.details, "lab_notes": [*result.notes, *verdict.reasons]}
        opp.updated_at = utc_now()
        self.store.put("opportunities", opp)
        return result
