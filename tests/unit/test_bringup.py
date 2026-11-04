"""0.18.0: Unbidden brings an application up by itself from the repository's own compose file."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml

from unbidden.operate import bringup

pytestmark = pytest.mark.unit

COMPOSE = """services:
  db:
    image: postgres:16
    environment:
      POSTGRES_PASSWORD: ${DB_PASSWORD}
  web:
    build: .
    container_name: fixed-web
    env_file: .env
    environment:
      DATABASE_URL: postgresql://postgres:${DB_PASSWORD}@db/app
      DEBUG: ${DEBUG:-0}
    ports:
      - "8000:8000"
    depends_on: [db]
"""


def _repo(tmp_path: Path, files: dict[str, str]) -> Path:
    repo = tmp_path / "shop"
    for path, text in files.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text(text)
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "x"], check=True)
    return repo


class FakeDocker:
    """`docker compose config` renders the file it is given (ports as compose's long form); `up` succeeds."""

    def __init__(self, up_ok: bool = True) -> None:
        self.calls: list[list[str]] = []
        self.up_ok = up_ok

    def __call__(self, argv: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(argv)
        if "config" in argv:
            files = [argv[i + 1] for i, a in enumerate(argv) if a == "-f"]
            data = yaml.safe_load(Path(files[0]).read_text())
            for spec in data["services"].values():
                spec["ports"] = [{"target": int(str(p).split(":")[-1]), "published": str(p).split(":")[0]}
                                 for p in spec.get("ports") or []]  # fmt: skip
            return subprocess.CompletedProcess(argv, 0, json.dumps(data), "")
        if "up" in argv:
            return subprocess.CompletedProcess(argv, 0 if self.up_ok else 1, "", "" if self.up_ok else "build failed")
        if "exec" in argv:
            return subprocess.CompletedProcess(argv, 0, "3\n", "")  # three tables: no migration needed
        return subprocess.CompletedProcess(argv, 0, "", "")


def _get(paths: dict[str, int]) -> bringup.Get:
    def get(url: str) -> httpx.Response | None:
        for path, code in paths.items():
            if url.endswith(path):
                return httpx.Response(code, json={"paths": {}} if path.endswith(".json") else None)
        return None

    return get


def test_the_app_comes_up_on_free_local_ports_with_generated_secrets(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {"compose.yml": COMPOSE, ".env.example": "DEBUG=1\nAPI_KEY=changeme\n", "Dockerfile": ""})
    docker = FakeDocker()
    result = bringup.up(repo, run=docker, get=_get({"/healthz": 200}), wait_s=5)
    assert result.ok and result.health_url is not None and result.health_url.endswith("/healthz")
    rendered = yaml.safe_load((repo / bringup.RENDERED).read_text())
    web = rendered["services"]["web"]
    assert "container_name" not in web and web["ports"][0]["host_ip"] == "127.0.0.1"
    assert web["ports"][0]["published"] != "8000" and web["labels"]["dev.unbidden.host"] == "unbidden-shop"
    assert "DB_PASSWORD" in result.generated_env  # needed by the compose file, said by nobody: generated
    env = (repo / bringup.ENV_FILE).read_text()
    assert "changeme" not in env and "DEBUG=" in env  # the example's placeholder secret is never used
    assert (repo / ".env").exists() and ".env" in (repo / ".git" / "info" / "exclude").read_text()
    assert result.deploy_steps[0][-4:] == ["up", "--deploy", "--build", "--json"]
    # A redeploy keeps the same ports and the same secrets.
    again = bringup.up(repo, deploy=True, run=docker, get=_get({"/healthz": 200}), wait_s=5)
    assert again.ok and again.ports == result.ports
    assert (repo / bringup.ENV_FILE).read_text() == env


def test_a_build_that_fails_is_said(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {"compose.yml": COMPOSE, "Dockerfile": ""})
    result = bringup.up(repo, run=FakeDocker(up_ok=False), get=_get({}), wait_s=1)
    assert not result.ok and "build failed" in (result.why or "")


def test_no_compose_file_is_said(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {"README.md": "x"})
    result = bringup.up(repo, run=FakeDocker(), get=_get({}), wait_s=1)
    assert not result.ok and "no compose file" in (result.why or "")


def test_health_is_found_from_openapi_then_usual_paths_then_django_admin() -> None:
    def get(url: str) -> httpx.Response | None:
        if url.endswith("/openapi.json"):
            return httpx.Response(200, json={"paths": {"/api/v1/utils/health-check/": {"get": {}}, "/x/{id}": {}}})
        if url.endswith("/api/v1/utils/health-check/"):
            return httpx.Response(200)
        return None

    assert bringup.find_health([("api", 1234)], get) == "http://127.0.0.1:1234/api/v1/utils/health-check/"
    admin = bringup.find_health([("web", 99)], _get({"/admin/login/": 200}))
    assert admin == "http://127.0.0.1:99/admin/login/"
    assert bringup.find_health([("web", 99)], _get({"/": 500})) is None


def test_migrations_are_found_from_the_repository(tmp_path: Path) -> None:
    django = _repo(tmp_path / "d", {"src/manage.py": "", "src/app/settings.py": ""})
    assert bringup.migration_command(django) == "cd src && python manage.py migrate --noinput"
    alembic = _repo(tmp_path / "a", {"backend/alembic.ini": ""})
    assert bringup.migration_command(alembic) == "cd backend && alembic upgrade head"


def test_variables_with_defaults_are_not_generated() -> None:
    assert bringup.referenced_variables(["a: ${A}\nb: ${B:-x}\nc: $C\nd: ${D:?need d}"]) == ["A", "C", "D"]


def test_the_command_is_refused_unless_allowed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`auto`: a person passes --yes, or the mandate is autonomous; `deny` refuses always."""
    import argparse

    from unbidden import cli
    from unbidden.contracts.guardian import Mandate

    called: list[bool] = []
    monkeypatch.setattr(bringup, "up", lambda *a, **k: called.append(True) or bringup.HostResult(why="x"))

    class Ws:
        repo = tmp_path

        def store(self) -> Any:
            class S:
                def append_event(self, *_: Any) -> None: ...
                def set_value(self, *_: Any) -> None: ...

            return S()

        def __init__(self, raw: dict[str, Any]) -> None:
            self.raw = raw

        def mandate(self) -> Mandate:
            return Mandate.model_validate(self.raw)

    def run(raw: dict[str, Any], **flags: Any) -> int:
        monkeypatch.setattr(cli.Workspace, "find", staticmethod(lambda: Ws(raw)))
        args = argparse.Namespace(action="up", yes=False, deploy=False, build=False, no_drill=True, json=True)
        for k, v in flags.items():
            setattr(args, k, v)
        return cli.cmd_host(args)

    assert run({"workspace": "w"}) == 2 and not called
    assert run({"workspace": "w"}, yes=True) == 1 and called
    called.clear()
    assert run({"workspace": "w", "operations": {"self_host": "deny"}}, yes=True) == 2 and not called
    assert run({"workspace": "w", "autonomy": {"merge_pull_requests": "allow"}}) == 1 and called


def test_an_example_secret_is_never_run_with() -> None:
    # TimeTracker refuses to start with its example SECRET_KEY.
    assert bringup.placeholder("your-secret-key-here") and bringup.placeholder("<generate>")
    assert bringup.placeholder("short") and not bringup.placeholder("9f2c4e1a7b3d5f60c8e2a4b6d8f01357")


def test_flask_migrate_and_the_applications_own_service(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {"migrations/alembic.ini": "", "migrations/env.py": "", "requirements.txt": "flask\n"})
    assert bringup.migration_command(repo) == "flask db upgrade"
    config = {"services": {"nginx": {"build": {"context": "nginx"}}, "app": {"build": {"context": "."}},
                           "db": {"image": "postgres:16"}}}  # fmt: skip
    assert bringup.built_service(config) == "app"


def test_a_proxy_that_only_answers_tls_is_reached_on_https() -> None:
    def get(url: str) -> httpx.Response | None:
        return httpx.Response(200) if url == "https://127.0.0.1:443/health" else httpx.Response(400)

    assert bringup.find_health([("nginx", 443)], get) == "https://127.0.0.1:443/health"


def test_the_drill_rolls_back_to_the_latest_commit_with_the_same_migrations(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {"app.py": "v1\n", "migrations/versions/001.py": "a\n"})
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
    (repo / "app.py").write_text("v2\n")
    subprocess.run([*git, "commit", "-qam", "code"], check=True)
    safe = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    (repo / "migrations/versions/002.py").write_text("b\n")
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "migration"], check=True)
    (repo / "app.py").write_text("v3\n")
    subprocess.run([*git, "commit", "-qam", "code again"], check=True)
    migrated = subprocess.run([*git, "rev-parse", "HEAD~1"], capture_output=True, text=True, check=True).stdout.strip()
    assert bringup.same_schema_previous(repo) == migrated  # HEAD~1 already has migration 002: same schema
    (repo / "migrations/versions/003.py").write_text("c\n")
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "another migration"], check=True)
    assert bringup.same_schema_previous(repo) is None or bringup.same_schema_previous(repo) != safe


def test_a_tool_beside_the_application_is_never_its_health() -> None:
    """misago: mailpit's web page answered `/` and was taken for the forum's health."""
    config = {"services": {"mailpit": {"image": "axllent/mailpit"}, "misago": {"build": {"context": "."}},
                           "postgres": {"image": "postgres:17"}, "web": {"image": "example/frontend"}}}  # fmt: skip
    ports = {"mailpit:8025": 1, "misago:8000": 2, "postgres:5432": 3, "web:80": 4}
    assert bringup.app_ports(config, ports) == [("misago", 2), ("web", 4)]
