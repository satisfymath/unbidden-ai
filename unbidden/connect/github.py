"""GitHub: what the granted token can do on the repository, as GitHub reports it. Read only here; writes (push,
pull request, merge) keep going through `publish/github.py` and their own autonomy rules."""

from __future__ import annotations

import httpx

from unbidden.connect.base import CheckResult, Failure, purpose
from unbidden.contracts.connection import Ability, ConnectionState
from unbidden.contracts.guardian import ConnectionGrant
from unbidden.guardian.credentials import broker

API = "https://api.github.com"


class GitHubConnector:
    kind = "github"

    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self.transport = transport

    def validate(self, grant: ConnectionGrant) -> list[str]:
        problems = [] if "/" in grant.location else ["location must be owner/name"]
        return problems + ([] if grant.credential_ref else ["a credential reference (a token's broker name)"])

    def check(self, grant: ConnectionGrant) -> CheckResult:
        token = broker().get(grant.credential_ref or "", purpose(grant.id))
        if not token:
            return CheckResult(
                ConnectionState.NEEDS_AUTHORIZATION,
                f"{grant.credential_ref} is not held by the broker",
                failure=Failure.AUTH,
                next_step=f"a person stores the token as {grant.credential_ref} in Unbidden's .env",
            )
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
        try:
            with httpx.Client(base_url=API, headers=headers, timeout=10, transport=self.transport) as client:
                response = client.get(f"/repos/{grant.location}")
        except httpx.HTTPError as exc:
            return CheckResult(ConnectionState.DEGRADED, f"GitHub unreachable: {exc}", failure=Failure.UNREACHABLE)
        if response.status_code == 401:
            return CheckResult(
                ConnectionState.REVOKED,
                "GitHub refused the token (401)",
                failure=Failure.AUTH,
                next_step=f"a person renews the token stored as {grant.credential_ref}",
            )
        if response.status_code in (403, 404):
            return CheckResult(
                ConnectionState.NEEDS_AUTHORIZATION,
                f"the token cannot see {grant.location} ({response.status_code})",
                failure=Failure.PERMISSION,
                next_step=f"give the token read access to {grant.location}",
            )
        permissions = response.json().get("permissions") or {}
        effective = ["read"] + (["write"] if permissions.get("push") else [])
        abilities = [
            Ability(
                kind="read",
                operations=["repository", "check runs", "pull requests"],
                known_by="checked: GitHub answered with the token",
            )
        ]
        if permissions.get("push"):
            abilities.append(
                Ability(
                    kind="write",
                    operations=["push branch", "pull request"],
                    known_by="checked: GitHub reports push permission for the token",
                )
            )
        return CheckResult(
            ConnectionState.CONNECTED,
            f"token can {'/'.join(effective)} {grant.location}",
            effective=effective,
            abilities=abilities,
            facts={"permissions": permissions},
        )
