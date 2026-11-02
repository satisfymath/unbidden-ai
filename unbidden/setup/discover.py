"""What setup finds on its own before asking anything: the repository and its GitHub remote, the scope, the
services and external connections the compose files declare (as committed at HEAD), the machine and its local
models, whether a model key is present, where the GitHub token comes from. One reading shared by the assistant,
`setup --show --json` and the app. Reads only: nothing here writes the store or asks the network beyond the local
Ollama."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from typing import Any

from unbidden.brain.hardware import Machine, Recommendation
from unbidden.guardian.credentials import broker
from unbidden.setup.github_access import Access, github_access
from unbidden.workspace import Workspace, github_slug

OLLAMA_DEFAULT = "http://localhost:11434"


@dataclass
class Found:
    name: str
    slug: str | None
    branch: str
    head: str | None  # None: no commit yet
    scope: list[tuple[str, bool, str]]
    machine: Machine
    installed: set[str]
    recommendation: Recommendation
    ollama_url: str
    ollama_present: bool  # the CLI or the server exists here, even without a model
    key_env: str
    key_present: bool
    github: Access
    compose_path: str | None
    services: list[tuple[str, str | None]] = field(default_factory=list)  # (name, data kind or None)
    external: list[tuple[str, str, str]] = field(default_factory=list)  # (kind, location, evidence)
    public: bool | None = None  # the store's cached visibility; None when never checked

    @property
    def local_model(self) -> bool:
        return self.recommendation.installed and self.recommendation.fits

    def option(self) -> tuple[str, str]:
        """The model option the facts amount to, and the text key of why (`models.why.*` in setup/text.py).
        Nothing here spends: `local` without a model is said."""
        if self.key_present and self.local_model:
            return "mixed", "models.why.mixed"
        if self.key_present:
            return "api", "models.why.api"
        if self.local_model:
            return "local", "models.why.local"
        return "local", "models.why.none"

    def as_dict(self) -> dict[str, Any]:
        from unbidden.setup.text import t

        option, why = self.option()
        why = t(why)
        return {
            "repository": self.slug or self.name,
            "branch": self.branch,
            "head": self.head,
            "scope": [{"name": n, "in_scope": ok, "note": note} for n, ok, note in self.scope],
            "machine": self.machine.describe,
            "ollama": {"url": self.ollama_url, "present": self.ollama_present, "models": sorted(self.installed)},
            "local_model": {"tag": self.recommendation.model.tag, "installed": self.local_model},
            "key": {"name": self.key_env, "present": self.key_present},
            "github": self.github.source,
            "compose": self.compose_path,
            "services": [{"name": n, "kind": k} for n, k in self.services],
            "external": [{"kind": k, "location": loc, "evidence": ev} for k, loc, ev in self.external],
            "option": option,
            "option_why": why,
        }


def _ollama_installed() -> bool:
    """The Ollama CLI is on this machine (a model may still be missing). Tests fake it."""
    import shutil

    return shutil.which("ollama") is not None


def _head(repo: Any) -> str | None:
    out = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
    return out.stdout.strip() if out.returncode == 0 and out.stdout.strip() else None


def _branch(repo: Any) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), "branch", "--show-current"], capture_output=True, text=True, check=False
    )
    return out.stdout.strip() or "HEAD"


def discover(ws: Workspace) -> Found:
    from unbidden.brain.hardware import detect, recommend  # looked up at call time: tests fake the machine
    from unbidden.runtime import installed_models
    from unbidden.setup import machine as machine_env

    repo = ws.repo
    head = _head(repo)
    scope: list[tuple[str, bool, str]] = []
    if head:
        try:
            from unbidden.observe.scope import diagnose

            scope = list(diagnose(repo))
        except Exception as exc:  # information, never a block
            scope = [("scope", False, f"not diagnosed ({type(exc).__name__})")]
    config = ws.config() if ws.initialized else None
    ollama_url = config.providers["ollama"].base_url if config and "ollama" in config.providers else OLLAMA_DEFAULT
    installed = installed_models(ollama_url)
    machine_ = detect()
    rec = recommend(machine_, installed)
    key_env = "MODEL_API_KEY"
    if config:
        key_env = next((p.key_env for p in config.providers.values() if p.key_env), key_env)
    github = github_access(ws)  # loads the env files into the broker as a side effect
    key_present = broker().has(key_env) or key_env in machine_env.read_env(machine_env.machine_env())
    compose_path: str | None = None
    services: list[tuple[str, str | None]] = []
    external: list[tuple[str, str, str]] = []
    if head:
        from unbidden.connect.registry import hints_of
        from unbidden.observe.compose import load_compose

        compose = load_compose(repo, "HEAD")
        if compose is not None:
            compose_path = compose.path
            services = [(s.name, s.data_kind) for s in compose.services.values()]
            external = hints_of(compose)
    public: bool | None = None
    if ws.initialized:
        try:
            cached = ws.store().get_value("repo_visibility")
            if isinstance(cached, dict) and "public" in cached:
                public = bool(cached["public"])
        except Exception:
            public = None
    return Found(
        name=repo.name,
        slug=github_slug(repo),
        branch=_branch(repo),
        head=head,
        scope=scope,
        machine=machine_,
        installed=installed,
        recommendation=rec,
        ollama_url=ollama_url,
        ollama_present=bool(installed) or _ollama_installed(),
        key_env=key_env,
        key_present=key_present,
        github=github,
        compose_path=compose_path,
        services=services,
        external=external,
        public=public,
    )
