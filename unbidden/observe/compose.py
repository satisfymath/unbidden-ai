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
DATA_IMAGES = re.compile(
    r"^(?:docker\.io/|ghcr\.io/valkey-io/)?(?:library/|valkey/)?(postgres|mysql|mariadb|redis|mongo|valkey)(?::|$)"
)
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
    labels: tuple[str, ...] = ()  # "key=value"

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
        # `KEY:` with no value, like `- KEY`, passes KEY from compose's environment.
        items = [(str(k), f"${{{k}}}" if v is None else str(v)) for k, v in raw.items()]  # pyright: ignore[reportUnknownVariableType]
    elif isinstance(raw, list):
        items = []
        for entry in raw:  # pyright: ignore[reportUnknownVariableType]
            key, eq, value = str(entry).partition("=")  # pyright: ignore[reportUnknownArgumentType]
            # `- KEY` without a value passes KEY from compose's environment, which includes the .env file.
            items.append((key, value if eq else f"${{{key}}}"))
    else:
        items = []
    for key, value in items:
        out[key] = interpolate(value, env, unresolved)
    return out


def _as_env_dict(raw: Any) -> dict[str, str | None]:
    if isinstance(raw, dict):
        return {str(k): None if v is None else str(v) for k, v in raw.items()}  # pyright: ignore[reportUnknownVariableType]
    if isinstance(raw, list):
        out: dict[str, str | None] = {}
        for entry in raw:  # pyright: ignore[reportUnknownVariableType]
            key, eq, value = str(entry).partition("=")  # pyright: ignore[reportUnknownArgumentType]
            out[key] = value if eq else None
        return out
    return {}


def _names(raw: Any) -> list[str]:
    return [str(x) for x in raw] if isinstance(raw, list) else [str(x) for x in raw] if isinstance(raw, dict) else []  # pyright: ignore[reportUnknownVariableType]


def _labels(raw: Any) -> list[str]:
    if isinstance(raw, dict):
        return [f"{k}={v}" for k, v in raw.items()]  # pyright: ignore[reportUnknownVariableType]
    return [str(x) for x in raw] if isinstance(raw, list) else []  # pyright: ignore[reportUnknownVariableType]


def merge_spec(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Compose's merge of one service across files: environment by key, depends_on and ports added up, mappings
    merged, anything else replaced by the later file."""
    merged = dict(base)
    for key, value in override.items():
        if key == "environment":
            env = {**_as_env_dict(base.get(key)), **_as_env_dict(value)}
            merged[key] = env
        elif key == "depends_on":
            merged[key] = list(dict.fromkeys([*_names(base.get(key)), *_names(value)]))
        elif key == "ports":
            merged[key] = [*(base.get(key) or []), *(value or [])]
        elif isinstance(value, dict) and isinstance(base.get(key), dict):
            merged[key] = merge_spec(base[key], value)  # pyright: ignore[reportUnknownArgumentType]
        else:
            merged[key] = value
    return merged


def load_compose(repo: Path, rev: str = "HEAD", files: list[str] | None = None) -> Compose | None:
    """The services of the compose files `files` (in order, later ones overriding), or of the first default file.

    Pass `files` when the deployment's own file list is known (`deployed_compose_files`): a project started with
    `-f compose.yaml -f compose.observability.yaml` runs services the default file does not declare.
    """
    texts: list[tuple[str, str]] = []
    for name in files or []:
        text = _git_show(repo, rev, name)
        if text is not None:
            texts.append((name, text))
    if not texts:
        for name in COMPOSE_FILES:
            text = _git_show(repo, rev, name)
            if text is not None:
                texts.append((name, text))
                break
        else:
            return None
    dotenv = parse_dotenv(_git_show(repo, rev, ".env") or "")
    specs: dict[str, dict[str, Any]] = {}
    for _, text in texts:
        raw = yaml.safe_load(text) or {}
        for service_name, spec in (raw.get("services") or {}).items():
            if isinstance(spec, dict):
                specs[service_name] = merge_spec(specs.get(service_name, {}), spec)  # pyright: ignore[reportUnknownArgumentType]
    unresolved: list[str] = []
    services: dict[str, Service] = {}
    for service_name, spec in specs.items():
        build = spec.get("build")
        context = build.get("context") if isinstance(build, dict) else build if isinstance(build, str) else None
        dockerfile = build.get("dockerfile") if isinstance(build, dict) else None
        # Build paths are interpolated like everything else (opentelemetry-demo: dockerfile: ${PAYMENT_DOCKERFILE}).
        context = interpolate(str(context), dotenv, unresolved) if context else None
        dockerfile = interpolate(str(dockerfile), dotenv, unresolved) if dockerfile else None
        health = (spec.get("healthcheck") or {}).get("test") or []
        services[service_name] = Service(
            name=service_name,
            image=interpolate(str(spec["image"]), dotenv, unresolved) if spec.get("image") else None,
            build_context=context,
            dockerfile=dockerfile,
            environment=_env_block(spec.get("environment"), dotenv, unresolved),
            depends_on=tuple(_names(spec.get("depends_on"))),
            ports=tuple(str(p) for p in spec.get("ports") or []),
            healthcheck=tuple(str(h) for h in health) if isinstance(health, list) else (str(health),),
            labels=tuple(_labels(spec.get("labels"))),
        )
    return Compose(path="+".join(n for n, _ in texts), services=services, unresolved=sorted(set(unresolved)))


def deployed_compose_files(repo: Path, labels: list[str]) -> list[str]:
    """The compose files a running project was started with (`com.docker.compose.project.config_files`), relative
    to the repository; files outside it are left out (they cannot be read from git)."""
    root = repo.resolve()
    found: list[str] = []
    for value in labels:
        for path in value.split(","):
            try:
                relative = Path(path).resolve().relative_to(root)
            except ValueError:
                continue
            if str(relative) not in found:
                found.append(str(relative))
    return found
