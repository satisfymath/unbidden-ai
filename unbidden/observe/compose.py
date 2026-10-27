"""Read a repository's compose file from git: services, images, environment, dependencies.

Variables are interpolated only from the tracked `.env` (values already public in the repository). An
untracked `.env` on disk is never read.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

COMPOSE_FILES = ("compose.yml", "compose.yaml", "docker-compose.yml", "docker-compose.yaml")
DATA_IMAGES = re.compile(r"^(?:docker\.io/)?(?:library/)?(postgres|mysql|mariadb|redis|mongo)(?::|$)")
_VAR = re.compile(
    r"\$\{(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?:(?P<op>:?[-?])(?P<arg>[^}]*))?\}|\$(?P<bare>[A-Za-z_][A-Za-z0-9_]*)"
)


@dataclass(frozen=True)
class Service:
    name: str
    image: str | None
    build_context: str | None
    dockerfile: str | None
    environment: dict[str, str]
    depends_on: tuple[str, ...]
    ports: tuple[str, ...]
    healthcheck: tuple[str, ...] = ()

    @property
    def data_kind(self) -> str | None:
        match = DATA_IMAGES.match(self.image or "")
        return match.group(1) if match else None


@dataclass(frozen=True)
class Compose:
    path: str
    services: dict[str, Service]
    unresolved: list[str] = field(default_factory=list[str])

    def data_services(self) -> list[Service]:
        return [s for s in self.services.values() if s.data_kind is not None]

    def app_service_for(self, directory: str) -> Service | None:
        """The service built from `directory` (its Dockerfile lives there), else one depending on a database."""
        for service in self.services.values():
            if service.dockerfile and service.dockerfile.startswith(f"{directory}/"):
                return service
            if service.build_context and service.build_context.strip("./") == directory:
                return service
        data = {s.name for s in self.data_services()}
        return next((s for s in self.services.values() if data & set(s.depends_on) and s.data_kind is None), None)


def _git_show(repo: Path, rev: str, path: str) -> str | None:
    out = subprocess.run(["git", "-C", str(repo), "show", f"{rev}:{path}"], capture_output=True, text=True, check=False)
    return out.stdout if out.returncode == 0 else None


def parse_dotenv(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.removeprefix("export ").partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip()] = value
    # Values may reference earlier ones, as in DATABASE_URL=...${POSTGRES_PASSWORD}...
    return {k: interpolate(v, values, []) for k, v in values.items()}


def interpolate(text: str, env: dict[str, str], unresolved: list[str]) -> str:
    def sub(m: re.Match[str]) -> str:
        name = m.group("name") or m.group("bare")
        op, arg = m.group("op"), m.group("arg") or ""
        value = env.get(name)
        if op in (":-", "-") and not value:
            return arg
        if value is None:
            unresolved.append(name)
            return ""
        return value

    return _VAR.sub(sub, text)


def _env_block(raw: Any, env: dict[str, str], unresolved: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    if isinstance(raw, dict):
        items = [(str(k), "" if v is None else str(v)) for k, v in raw.items()]  # pyright: ignore[reportUnknownVariableType]
    elif isinstance(raw, list):
        items = [(str(e).partition("=")[0], str(e).partition("=")[2]) for e in raw]  # pyright: ignore[reportUnknownVariableType]
    else:
        items = []
    for key, value in items:
        out[key] = interpolate(value, env, unresolved)
    return out


def load_compose(repo: Path, rev: str = "HEAD") -> Compose | None:
    for name in COMPOSE_FILES:
        text = _git_show(repo, rev, name)
        if text is not None:
            break
    else:
        return None
    dotenv = parse_dotenv(_git_show(repo, rev, ".env") or "")
    raw = yaml.safe_load(text) or {}
    unresolved: list[str] = []
    services: dict[str, Service] = {}
    for service_name, spec in (raw.get("services") or {}).items():
        if not isinstance(spec, dict):
            continue
        build = spec.get("build")
        context = build.get("context") if isinstance(build, dict) else build if isinstance(build, str) else None
        dockerfile = build.get("dockerfile") if isinstance(build, dict) else None
        depends = spec.get("depends_on") or []
        health = (spec.get("healthcheck") or {}).get("test") or []
        services[service_name] = Service(
            name=service_name,
            image=interpolate(str(spec["image"]), dotenv, unresolved) if spec.get("image") else None,
            build_context=context,
            dockerfile=dockerfile,
            environment=_env_block(spec.get("environment"), dotenv, unresolved),
            depends_on=tuple(depends if isinstance(depends, list) else depends.keys()),
            ports=tuple(str(p) for p in spec.get("ports") or []),
            healthcheck=tuple(str(h) for h in health) if isinstance(health, list) else (str(health),),
        )
    return Compose(path=name, services=services, unresolved=sorted(set(unresolved)))
