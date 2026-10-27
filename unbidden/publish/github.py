"""Push a proposal branch and open its pull request, idempotently, under the mandate.

The token is read from the environment by a GIT_ASKPASS helper and by the HTTP client; it is never part of
a command line, a remote URL, an event or a log line. Branches are only ever created under `unbidden/`, never
force-pushed, and never the base branch.
"""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from unbidden.contracts.events import Event, EventType
from unbidden.contracts.experiment import Proposal, ProposalStatus, PullRequestRef
from unbidden.contracts.guardian import ActionRequest, Decision, EgressAttempt, Mandate
from unbidden.guardian.approvals import consume, find_valid
from unbidden.guardian.egress import evaluate_github
from unbidden.guardian.policy import GITHUB_HOSTS, PolicyEngine
from unbidden.store import Store

ACTOR = "publisher"
API = "https://api.github.com"
CAPABILITY = "github.open_pull_request"


class PublishError(RuntimeError):
    pass


class NeedsApproval(PublishError):
    pass


class GitHubClient:
    def __init__(self, slug: str, token_env: str, *, transport: httpx.BaseTransport | None = None) -> None:
        from unbidden.guardian.credentials import broker

        token = broker().get(token_env, "github")
        if not token:
            raise PublishError(f"{token_env} is not set; unbidden cannot reach GitHub")
        self.slug = slug
        self._http = httpx.Client(
            base_url=API,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30,
            transport=transport,
        )

    def _check(self, response: httpx.Response) -> Any:
        if response.status_code >= 400:
            raise PublishError(f"GitHub {response.status_code}: {response.text[:300]}")
        return response.json()

    def find_pr(self, branch: str) -> dict[str, Any] | None:
        owner = self.slug.split("/")[0]
        pulls = self._check(
            self._http.get(f"/repos/{self.slug}/pulls", params={"head": f"{owner}:{branch}", "state": "all"})
        )
        return pulls[0] if pulls else None

    def create_pr(self, *, title: str, body: str, head: str, base: str) -> dict[str, Any]:
        return self._check(
            self._http.post(
                f"/repos/{self.slug}/pulls", json={"title": title, "body": body, "head": head, "base": base}
            )
        )

    def get_pr(self, number: int) -> dict[str, Any]:
        return self._check(self._http.get(f"/repos/{self.slug}/pulls/{number}"))

    def merge_pr(self, number: int, *, sha: str, method: str = "squash") -> dict[str, Any]:
        """Merge only if the pull request's head is still exactly the commit that was measured."""
        return self._check(
            self._http.put(f"/repos/{self.slug}/pulls/{number}/merge", json={"sha": sha, "merge_method": method})
        )

    def branch_head(self, branch: str) -> str:
        return self._check(self._http.get(f"/repos/{self.slug}/branches/{branch}"))["commit"]["sha"]


def push_branch(repo: Path, slug: str, branch: str, commit: str, token_env: str, base_branch: str) -> None:
    if not branch.startswith("unbidden/") or branch == base_branch:
        raise PublishError(f"refusing to push {branch!r}: only unbidden/ branches are ever pushed")
    with tempfile.TemporaryDirectory(prefix="unbidden-askpass-") as tmp:
        helper = Path(tmp) / "askpass.sh"
        # Answers git's username and password prompts from the environment; the token never touches argv.
        helper.write_text(
            '#!/bin/sh\ncase "$1" in\n  Username*) echo "x-access-token" ;;\n'
            f'  *) printf "%s" "${token_env}" ;;\nesac\n'
        )
        helper.chmod(stat.S_IRWXU)
        from unbidden.guardian.credentials import broker

        # The token reaches only this git process, through the helper it calls; never argv, never os.environ.
        env = {
            **os.environ,
            "GIT_ASKPASS": str(helper),
            "GIT_TERMINAL_PROMPT": "0",
            token_env: broker().get(token_env, "github") or "",
        }
        result = subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "-c",
                "credential.helper=",
                "push",
                f"https://github.com/{slug}.git",
                f"{commit}:refs/heads/{branch}",
            ],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        if result.returncode != 0:
            raise PublishError(f"push of {branch} failed: {result.stderr.strip()[-400:]}")


@dataclass
class Publisher:
    repo: Path
    store: Store
    mandate: Mandate
    client: GitHubClient | None = None

    def _client(self) -> GitHubClient:
        if self.client is None:
            policy = self.mandate.egress.github
            if policy.repository is None:
                raise PublishError("the mandate names no GitHub repository")
            self.client = GitHubClient(policy.repository, policy.token_env)
        return self.client

    def open_count(self) -> int:
        return len(self.store.list("proposals", Proposal, status=ProposalStatus.PR_OPENED.value))

    def publish(self, proposal: Proposal, patch: str) -> Proposal:
        policy = self.mandate.egress.github
        if proposal.status in (ProposalStatus.PR_OPENED, ProposalStatus.MERGED):
            return proposal
        if proposal.status is ProposalStatus.PUBLISHING:
            raise PublishError("another run is already publishing this proposal")
        approval = find_valid(self.store, CAPABILITY, proposal.id)
        verdict = PolicyEngine(self.mandate).evaluate(
            ActionRequest(capability=CAPABILITY, purpose=proposal.title, destinations=list(GITHUB_HOSTS)),
            approved=approval is not None,
        )
        if verdict.decision is Decision.REQUIRE_APPROVAL:
            raise NeedsApproval(f"run `unbidden approve {proposal.opportunity_id}` to open this pull request")
        if not verdict.allowed:
            raise PublishError("; ".join(verdict.reasons))
        if self.open_count() >= policy.max_open_pull_requests:
            raise PublishError(f"{policy.max_open_pull_requests} pull requests are already open")

        payload = f"{proposal.title}\n\n{proposal.body_md}\n\n{patch}"
        egress = evaluate_github(self.mandate, "api.github.com", payload)
        attempt = EgressAttempt(
            status="allowed_pending" if egress.allowed else "blocked",
            purpose="github.pull_request",
            destination="github.com",
            provider="github",
            verdict=egress,
            payload=payload if egress.allowed else f"sha256:{egress.payload_sha256}",
        )
        self.store.put("egress", attempt)
        self.store.append_event(
            Event(
                type=EventType.EGRESS_ALLOWED if egress.allowed else EventType.EGRESS_BLOCKED,
                actor=ACTOR,
                entity_id=attempt.id,
                correlation_id=proposal.opportunity_id,
                payload={"destination": "github.com", "bytes": egress.payload_bytes, "reasons": egress.reasons},
            )
        )
        if not egress.allowed:
            raise PublishError("; ".join(egress.reasons))

        proposal.status = ProposalStatus.PUBLISHING
        self.store.put("proposals", proposal)
        try:
            client = self._client()
            existing = client.find_pr(proposal.branch)
            if existing is None:
                push_branch(
                    self.repo, client.slug, proposal.branch, proposal.commit_sha, policy.token_env, policy.base_branch
                )
                pr = client.create_pr(
                    title=proposal.title, body=proposal.body_md, head=proposal.branch, base=policy.base_branch
                )
            else:
                pr = existing
        except Exception:
            proposal.status = ProposalStatus.READY
            self.store.put("proposals", proposal)
            attempt.status = "failed"
            self.store.put("egress", attempt)
            raise
        if approval is not None:
            consume(self.store, approval)
        attempt.status = "allowed_sent"
        self.store.put("egress", attempt)
        proposal.status = ProposalStatus.PR_OPENED
        proposal.pr = PullRequestRef(number=pr["number"], url=pr["html_url"], head_sha=pr["head"]["sha"])
        proposal.egress_attempt_ids = [*proposal.egress_attempt_ids, attempt.id]
        self.store.put("proposals", proposal)
        self.store.append_event(
            Event(
                type=EventType.PROPOSAL_PUBLISHED,
                actor=ACTOR,
                entity_id=proposal.id,
                correlation_id=proposal.opportunity_id,
                payload={"url": proposal.pr.url, "number": pr["number"]},
            )
        )
        return proposal

    def merge(self, proposal: Proposal) -> Proposal:
        """Autonomous merge: L4 or better, pinned to the measured commit, within the hourly limit, never held."""
        from datetime import timedelta

        from unbidden.contracts.common import EvidenceLevel, utc_now
        from unbidden.operate.deploy import check

        if proposal.status is not ProposalStatus.PR_OPENED or proposal.pr is None:
            raise PublishError("only an open pull request can be merged")
        if proposal.evidence_level < EvidenceLevel.FUNCTIONAL_VALIDATION:
            raise PublishError(f"evidence L{int(proposal.evidence_level)} is below L4; a person merges this one")
        sequence: list[str] = self.store.get_value("deploy_sequence", [])
        if len(sequence) >= 2 and self.store.get_value(f"verdict_of:{len(sequence) - 1}") is None:
            # One change at a time: until the last deploy has its verdict, another merge would blur what it did.
            raise PublishError(f"deploy {sequence[-1][:12]} has no verdict yet; merging waits for it")
        check(
            self.store,
            self.mandate,
            "github.merge_pull_request",
            proposal.title,
            rate_key="merges",
            limit=self.mandate.operations.max_merges_per_hour,
        )
        merged = self._client().merge_pr(proposal.pr.number, sha=proposal.commit_sha)
        stamps: list[str] = self.store.get_value("merges", [])
        since = (utc_now() - timedelta(hours=24)).isoformat()
        self.store.set_value("merges", [*(s for s in stamps if s >= since), utc_now().isoformat()])
        proposal.status = ProposalStatus.MERGED
        merge_sha = merged.get("sha")
        if isinstance(merge_sha, str) and len(merge_sha) == 40:
            proposal.merge_sha = merge_sha
        self.store.put("proposals", proposal)
        self.store.append_event(
            Event(
                type=EventType.MERGED,
                actor=ACTOR,
                entity_id=proposal.id,
                correlation_id=proposal.opportunity_id,
                payload={"number": proposal.pr.number, "sha": merged.get("sha"), "measured": proposal.commit_sha},
            )
        )
        return proposal

    def poll(self, proposal: Proposal) -> Proposal:
        """Follow an open pull request: merged, closed, or stale because its base moved."""
        if proposal.status is not ProposalStatus.PR_OPENED or proposal.pr is None:
            return proposal
        client = self._client()
        pr = client.get_pr(proposal.pr.number)
        if pr.get("merged_at"):
            proposal.status = ProposalStatus.MERGED
        elif pr.get("state") == "closed":
            proposal.status = ProposalStatus.CLOSED_UNMERGED
        elif client.branch_head(self.mandate.egress.github.base_branch) != proposal.base_sha:
            proposal.status = ProposalStatus.STALE
            self.store.append_event(
                Event(
                    type=EventType.PROPOSAL_STALE,
                    actor=ACTOR,
                    entity_id=proposal.id,
                    correlation_id=proposal.opportunity_id,
                    payload={"reason": "the base branch moved; the evidence must be measured again"},
                )
            )
        self.store.put("proposals", proposal)
        return proposal
