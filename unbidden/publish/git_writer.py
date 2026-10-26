"""Create a commit on top of a base without touching the working tree, the index or the current branch.

Uses git plumbing with a private index file, so the team's checkout is never modified.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

from unbidden.contracts.common import Sha

AUTHOR_NAME = "Unbidden"
AUTHOR_EMAIL = "unbidden@users.noreply.github.com"


class GitWriteError(RuntimeError):
    pass


def _git(repo: Path, *args: str, env: dict[str, str] | None = None, input_: bytes | None = None) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, input=input_, env=env, check=False)
    if result.returncode != 0:
        raise GitWriteError(f"git {' '.join(args[:2])}: {result.stderr.decode(errors='replace').strip()}")
    return result.stdout.decode().strip()


def branch_name(title: str, opportunity_id: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40].strip("-")
    return f"unbidden/{slug}-{opportunity_id[-6:]}"


def commit_files(repo: Path, base: Sha, files: dict[str, str], message: str, branch: str) -> Sha:
    """Commit `files` on top of `base` as `refs/heads/<branch>`. Never moves an existing branch elsewhere."""
    existing = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", "-q", f"refs/heads/{branch}"],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    if existing.returncode == 0:
        raise GitWriteError(f"branch {branch} already exists; refusing to overwrite it")
    with tempfile.TemporaryDirectory(prefix="unbidden-index-") as tmp:
        env = {
            **os.environ,
            "GIT_INDEX_FILE": str(Path(tmp) / "index"),
            "GIT_AUTHOR_NAME": AUTHOR_NAME,
            "GIT_AUTHOR_EMAIL": AUTHOR_EMAIL,
            "GIT_COMMITTER_NAME": AUTHOR_NAME,
            "GIT_COMMITTER_EMAIL": AUTHOR_EMAIL,
        }
        _git(repo, "read-tree", base, env=env)
        for path, content in sorted(files.items()):
            blob = _git(repo, "hash-object", "-w", "--stdin", env=env, input_=content.encode())
            mode = "100644"
            listed = _git(repo, "ls-tree", base, "--", path, env=env)
            if listed:
                mode = listed.split()[0]
            _git(repo, "update-index", "--add", "--cacheinfo", f"{mode},{blob},{path}", env=env)
        tree = _git(repo, "write-tree", env=env)
        commit = _git(repo, "commit-tree", tree, "-p", base, "-F", "-", env=env, input_=message.encode())
        _git(repo, "update-ref", f"refs/heads/{branch}", commit, "0" * 40, env=env)
    return commit
