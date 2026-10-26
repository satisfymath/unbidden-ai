from __future__ import annotations

import json
import subprocess
from pathlib import Path

import httpx
import pytest

from unbidden.contracts.common import EvidenceLevel
from unbidden.contracts.experiment import Proposal, ProposalStatus
from unbidden.contracts.guardian import EgressAttempt, Mandate
from unbidden.guardian.approvals import grant
from unbidden.publish import github
from unbidden.publish.git_writer import GitWriteError, branch_name, commit_files
from unbidden.publish.github import CAPABILITY, GitHubClient, NeedsApproval, Publisher, PublishError
from unbidden.store import Store

pytestmark = pytest.mark.unit


@pytest.fixture
def repo(tmp_path: Path) -> tuple[Path, str]:
    git = ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True)
    (tmp_path / "a.ts").write_text("let a = 1;\n")
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "init"], check=True)
    sha = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    return tmp_path, sha


def test_commit_does_not_touch_the_checkout(repo: tuple[Path, str]) -> None:
    path, base = repo
    branch = branch_name("2 tsc errors in a.ts", "opp_123456789")
    commit = commit_files(path, base, {"a.ts": "const a = 1;\n"}, "fix: a", branch)
    assert (path / "a.ts").read_text() == "let a = 1;\n"
    status = subprocess.run(["git", "-C", str(path), "status", "--porcelain"], capture_output=True, text=True)
    assert status.stdout == ""
    shown = subprocess.run(["git", "-C", str(path), "show", f"{commit}:a.ts"], capture_output=True, text=True)
    assert shown.stdout == "const a = 1;\n"
    with pytest.raises(GitWriteError):
        commit_files(path, base, {"a.ts": "x\n"}, "again", branch)


def proposal(base: str) -> Proposal:
    return Proposal(
        opportunity_id="opp_1", experiment_id="exp_1", branch="unbidden/fix-a", base_sha=base, commit_sha=base,
        title="fix: a", body_md="evidence", evidence_level=EvidenceLevel.FUNCTIONAL_VALIDATION,
    )  # fmt: skip


def fake_github(created: list[dict[str, object]]) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer t0ken-value-123"
        if request.method == "GET" and request.url.path.endswith("/pulls"):
            return httpx.Response(200, json=[])
        if request.method == "POST":
            created.append(json.loads(request.content))
            return httpx.Response(201, json={"number": 7, "html_url": "https://github.com/acme/shop/pull/7",
                                             "head": {"sha": "b" * 40}})  # fmt: skip
        return httpx.Response(404)

    return httpx.MockTransport(handle)


def test_publish_needs_approval_then_opens_once(
    store: Store, mandate: Mandate, repo: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    path, base = repo
    monkeypatch.setenv("GITHUB_TOKEN", "t0ken-value-123")
    pushed: list[str] = []
    monkeypatch.setattr(github, "push_branch", lambda *a, **k: pushed.append(a[2]))  # type: ignore[misc]
    created: list[dict[str, object]] = []
    client = GitHubClient("acme/shop", "GITHUB_TOKEN", transport=fake_github(created))
    publisher = Publisher(path, store, mandate, client)
    prop = proposal(base)
    store.put("proposals", prop)
    with pytest.raises(NeedsApproval):
        publisher.publish(prop, "+fix")
    grant(store, CAPABILITY, prop.id, "david", ttl=__import__("datetime").timedelta(hours=1))
    opened = publisher.publish(prop, "+fix")
    assert opened.status is ProposalStatus.PR_OPENED and opened.pr is not None and opened.pr.number == 7
    assert pushed == ["unbidden/fix-a"]
    assert created[0]["head"] == "unbidden/fix-a" and created[0]["base"] == "main"
    assert publisher.publish(opened, "+fix") is opened  # idempotent
    attempt = store.list("egress", EgressAttempt)[-1]
    assert attempt.status == "allowed_sent" and "evidence" in attempt.payload


def test_secret_in_patch_blocks_publishing(
    store: Store, mandate: Mandate, repo: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    path, base = repo
    monkeypatch.setenv("GITHUB_TOKEN", "t0ken-value-123")
    prop = proposal(base)
    grant(store, CAPABILITY, prop.id, "david", ttl=__import__("datetime").timedelta(hours=1))
    publisher = Publisher(path, store, mandate, GitHubClient("acme/shop", "GITHUB_TOKEN", transport=fake_github([])))
    with pytest.raises(PublishError):
        publisher.publish(prop, "+DB_PASSWORD=hunter2hunter2")
    assert store.list("egress", EgressAttempt)[-1].status == "blocked"


def test_only_unbidden_branches_are_pushed(tmp_path: Path) -> None:
    with pytest.raises(PublishError):
        github.push_branch(tmp_path, "acme/shop", "main", "a" * 40, "GITHUB_TOKEN", "main")
