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


def test_no_merge_while_the_last_deploy_awaits_its_verdict(
    store: Store, mandate: Mandate, repo: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from unbidden.contracts.experiment import PullRequestRef

    path, base = repo
    monkeypatch.setenv("GITHUB_TOKEN", "t0ken-value-123")
    mandate.autonomy.merge_pull_requests = __import__(
        "unbidden.contracts.guardian", fromlist=["Autonomy"]
    ).Autonomy.ALLOW
    prop = proposal(base)
    prop.status = ProposalStatus.PR_OPENED
    prop.pr = PullRequestRef(number=7, url="u", head_sha=base)
    store.set_value("deploy_sequence", ["a" * 40, "b" * 40])
    publisher = Publisher(path, store, mandate, GitHubClient("acme/shop", "GITHUB_TOKEN", transport=fake_github([])))
    with pytest.raises(PublishError, match="no verdict yet"):
        publisher.merge(prop)


def pr_github(head: str, runs: list[dict[str, object]], merged: list[str]) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/check-runs"):
            return httpx.Response(200, json={"total_count": len(runs), "check_runs": runs})
        if request.method == "PUT" and path.endswith("/merge"):
            merged.append(path)
            return httpx.Response(200, json={"sha": "c" * 40, "merged": True})
        if path.endswith("/pulls/7"):
            return httpx.Response(200, json={"number": 7, "head": {"sha": head}})
        return httpx.Response(404)

    return httpx.MockTransport(handle)


def open_for_merge(
    store: Store,
    mandate: Mandate,
    path: Path,
    sha: str,
    monkeypatch: pytest.MonkeyPatch,
    transport: httpx.MockTransport,
) -> tuple[Publisher, Proposal]:
    from unbidden.contracts.experiment import PullRequestRef
    from unbidden.contracts.guardian import Autonomy

    monkeypatch.setenv("GITHUB_TOKEN", "t0ken-value-123")
    mandate.autonomy.merge_pull_requests = Autonomy.ALLOW
    prop = proposal(sha)
    prop.status = ProposalStatus.PR_OPENED
    prop.pr = PullRequestRef(number=7, url="u", head_sha=sha)
    return Publisher(path, store, mandate, GitHubClient("acme/shop", "GITHUB_TOKEN", transport=transport)), prop


def with_workflow(path: Path) -> str:
    git = ["git", "-C", str(path), "-c", "user.name=t", "-c", "user.email=t@t"]
    (path / ".github" / "workflows").mkdir(parents=True)
    (path / ".github" / "workflows" / "ci.yml").write_text("on: push\njobs: {}\n")
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "ci"], check=True)
    return subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()


DONE: dict[str, object] = {"status": "completed", "conclusion": "success", "name": "test"}


@pytest.mark.parametrize(
    ("runs", "why"),
    [
        ([], "none has run"),  # A5: the first poll, before the PR's CI started
        ([{"status": "in_progress", "conclusion": None, "name": "test"}], "still running"),
        ([DONE, {"status": "completed", "conclusion": "failure", "name": "lint"}], "is red"),
        ([{"status": "completed", "conclusion": "cancelled", "name": "test"}], "is unknown"),
    ],
)
def test_no_merge_until_the_pull_requests_own_ci_passed(
    runs: list[dict[str, object]], why: str, store: Store, mandate: Mandate, repo: tuple[Path, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    path, _ = repo
    sha = with_workflow(path)
    merged: list[str] = []
    publisher, prop = open_for_merge(store, mandate, path, sha, monkeypatch, pr_github(sha, runs, merged))
    with pytest.raises(PublishError, match=why):
        publisher.merge(prop)
    assert merged == []


def test_a_green_pr_ci_on_the_measured_commit_merges(
    store: Store, mandate: Mandate, repo: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    path, _ = repo
    sha = with_workflow(path)
    merged: list[str] = []
    publisher, prop = open_for_merge(store, mandate, path, sha, monkeypatch, pr_github(sha, [DONE], merged))
    assert publisher.merge(prop).status is ProposalStatus.MERGED and merged


def test_no_merge_when_the_pull_request_moved_past_the_measured_commit(
    store: Store, mandate: Mandate, repo: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    path, sha = repo
    merged: list[str] = []
    publisher, prop = open_for_merge(store, mandate, path, sha, monkeypatch, pr_github("d" * 40, [DONE], merged))
    with pytest.raises(PublishError, match="not the measured"):
        publisher.merge(prop)


def test_a_repository_without_ci_merges_on_the_labs_evidence(
    store: Store, mandate: Mandate, repo: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    path, sha = repo
    merged: list[str] = []
    publisher, prop = open_for_merge(store, mandate, path, sha, monkeypatch, pr_github(sha, [], merged))
    assert publisher.merge(prop).status is ProposalStatus.MERGED


def test_an_autonomous_deploy_needs_a_merged_proposal_with_l4_contained_in_the_target(
    store: Store, repo: tuple[Path, str]
) -> None:
    from unbidden.operate.deploy import OperationRefused, merged_evidence

    path, sha = repo
    with pytest.raises(OperationRefused, match="no merged proposal"):
        merged_evidence(path, store, None, sha)
    prop = proposal(sha)
    store.put("proposals", prop)
    with pytest.raises(OperationRefused, match="not merged"):
        merged_evidence(path, store, prop.id, sha)
    prop.status = ProposalStatus.MERGED
    prop.evidence_level = EvidenceLevel.LAB_IMPROVEMENT
    store.put("proposals", prop)
    with pytest.raises(OperationRefused, match="below L4"):
        merged_evidence(path, store, prop.id, sha)
    prop.evidence_level = EvidenceLevel.FUNCTIONAL_VALIDATION
    prop.merge_sha = with_workflow(path)  # a merge the target below does not contain
    store.put("proposals", prop)
    with pytest.raises(OperationRefused, match="does not contain"):
        merged_evidence(path, store, prop.id, sha)
    merged_evidence(path, store, prop.id, prop.merge_sha)
