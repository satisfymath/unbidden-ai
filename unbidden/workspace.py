"""A workspace is a git repository plus its `.unbidden/` directory: config, mandate and state."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import yaml

from unbidden.config import Config, load_config
from unbidden.contracts.guardian import Mandate
from unbidden.guardian.killswitch import KillSwitch
from unbidden.guardian.mandate import load_mandate
from unbidden.store import Store

DIRNAME = ".unbidden"


class WorkspaceError(RuntimeError):
    pass


def repo_root(start: Path) -> Path:
    out = subprocess.run(
        ["git", "-C", str(start), "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False
    )
    if out.returncode != 0:
        raise WorkspaceError(f"{start} is not inside a git repository")
    return Path(out.stdout.strip())


def head_sha(repo: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()


def default_branch(repo: Path) -> str:
    """The remote's default branch (what pull requests target), not an assumed 'main'."""
    out = subprocess.run(
        ["git", "-C", str(repo), "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if out.returncode == 0 and "/" in out.stdout:
        return out.stdout.strip().split("/", 1)[1]
    current = subprocess.run(
        ["git", "-C", str(repo), "branch", "--show-current"], capture_output=True, text=True, check=False
    ).stdout.strip()
    return current or "main"


def default_mandate(workspace: str, github_repo: str | None, base_branch: str = "main") -> dict[str, object]:
    """A supervised start: observe and experiment freely, ask before anything reaches GitHub, never merge."""
    return {
        "mandate": {
            "workspace": workspace,
            "priorities": ["correctness", "maintainability", "security"],
            "business_constraints": {"maximum_monthly_spend_usd": 10},
            "autonomy": {
                "observe": "allow",
                "run_experiments": "allow",
                "provision_dependencies": "allow",
                "delegate_synthetic": "allow",
                "open_pull_requests": "require_approval",
                "merge_pull_requests": "deny",
                "deploy": "deny",
                "rollback": "deny",
                "use_new_capabilities": "require_approval",
            },
            "egress": {
                "package_registries": ["registry.npmjs.org", "pypi.org", "files.pythonhosted.org"],
                "remote_models": {"destinations": ["api.meta.ai"], "max_payload_bytes": 20000},
                "github": {"repository": github_repo, "base_branch": base_branch, "max_open_pull_requests": 3},
            },
            "evaluation": {"minimum_evidence_for_proposal": 4},
        }
    }


def github_slug(repo: Path) -> str | None:
    out = subprocess.run(
        ["git", "-C", str(repo), "remote", "get-url", "origin"], capture_output=True, text=True, check=False
    )
    url = out.stdout.strip()
    for marker in ("github.com:", "github.com/"):
        if marker in url:
            return url.split(marker, 1)[1].removesuffix(".git").strip("/") or None
    if url.startswith("git@github-") and ":" in url:  # ssh host aliases such as git@github-work:owner/repo
        return url.split(":", 1)[1].removesuffix(".git") or None
    return None


@dataclass
class Workspace:
    repo: Path

    @property
    def dir(self) -> Path:
        return self.repo / DIRNAME

    @property
    def mandate_path(self) -> Path:
        return self.dir / "mandate.yaml"

    @property
    def config_path(self) -> Path:
        return self.dir / "config.yaml"

    @property
    def initialized(self) -> bool:
        return self.mandate_path.exists()

    @classmethod
    def find(cls, start: Path | None = None) -> Workspace:
        return cls(repo_root(start or Path.cwd()))

    def init(self) -> bool:
        """Create `.unbidden/` without touching tracked files. Returns False if it already existed."""
        if self.initialized:
            return False
        self.dir.mkdir(exist_ok=True)
        mandate = default_mandate(self.repo.name, github_slug(self.repo), default_branch(self.repo))
        self.mandate_path.write_text(yaml.safe_dump(mandate, sort_keys=False))
        self.config_path.write_text(
            "# Overrides of unbidden's defaults. See `unbidden doctor` for the effective routing.\n{}\n"
        )
        exclude = self.repo / ".git" / "info" / "exclude"
        if exclude.parent.exists():
            lines = exclude.read_text().splitlines() if exclude.exists() else []
            if f"{DIRNAME}/" not in lines:
                exclude.write_text("\n".join([*lines, f"{DIRNAME}/"]) + "\n")
        return True

    def require(self) -> None:
        if not self.initialized:
            raise WorkspaceError(f"{self.repo} has no {DIRNAME}/ yet; run `unbidden init` first")

    def mandate(self) -> Mandate:
        return load_mandate(self.mandate_path)

    def config(self) -> Config:
        return load_config(self.config_path)

    def store(self) -> Store:
        return Store(self.dir / "state.db")

    def killswitch(self) -> KillSwitch:
        return KillSwitch(self.dir)

    def repo_public(self, store: Store, *, max_age_hours: float = 6) -> bool:
        """Whether GitHub confirms this repository is public. Anything else (no remote, an error, a private
        repository) is treated as private: code may only leave as a public repository's code."""
        from datetime import UTC, datetime, timedelta

        import httpx

        slug = github_slug(self.repo)
        if slug is None:
            return False
        cached = store.get_value("repo_visibility") or {}
        fresh = (
            cached.get("slug") == slug
            and cached.get("checked_at", "") > (datetime.now(UTC) - timedelta(hours=max_age_hours)).isoformat()
        )
        if fresh:
            return bool(cached.get("public"))
        public = False
        try:
            token = os.environ.get("GITHUB_TOKEN")
            headers = {
                "Accept": "application/vnd.github+json",
                **({"Authorization": f"Bearer {token}"} if token else {}),
            }
            response = httpx.get(f"https://api.github.com/repos/{slug}", headers=headers, timeout=10)
            public = response.status_code == 200 and response.json().get("private") is False
        except (httpx.HTTPError, ValueError):
            public = False
        store.set_value(
            "repo_visibility", {"slug": slug, "public": public, "checked_at": datetime.now(UTC).isoformat()}
        )
        return public

    def load_env(self) -> None:
        """Read unbidden's own `.env` files into the environment without overriding what is already set.

        The observed repository's `.env` is never read: its secrets are not ours to hold.
        """
        for path in (self.dir / ".env", Path.home() / ".unbidden" / ".env"):
            if not path.exists():
                continue
            for line in path.read_text().splitlines():
                key, sep, value = line.partition("=")
                key = key.strip()
                if sep and key and not key.startswith("#"):
                    os.environ.setdefault(key, value.strip().strip("'\""))
