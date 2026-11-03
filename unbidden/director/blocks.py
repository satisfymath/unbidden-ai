"""What stopped a piece of work, and what would let it continue: a request to a person only when one can unblock it.

Found on Conduit (frozen run 9ef6a60): every experiment failed to provision (a compiler and `pg_config` from Debian's
archive, which the mandate did not list), and the one thing listed for a person was GitHub access, which nothing
needed. Each block now records the operation that stopped, the evidence, the kind, the minimum that would unblock it,
and what continues once it is given. Kinds, kept apart:

- `pending_person`: a person can unblock it, and the request names exactly what (a registry, a grant, an approval);
- `compatibility`: the project cannot be reproduced here as declared (a package that does not build, no supported
  interpreter); nothing a person grants fixes it, the cause is said;
- `missing_capability`: Unbidden lacks a way to do it (no integration could be validated);
- `unavailable`: a service did not answer (retried later);
- `not_viable`: the work cannot produce evidence (no test to run, nothing to measure).

An access that was found but blocks nothing (a discovered repository nobody granted) is `optional`: listed apart, with
what it would enable, never as a requirement.

One request per need (stage 8 regression, adb803d): five experiments blocked on the same registry were five requests
and five answers for one grant. A block is now keyed by its kind and its minimum; the operations and jobs it holds
are listed on it. A job blocked on a person is parked, without spending its attempts, and `release` puts it back in
the queue as soon as the mandate shows the need met (the same regression: after the grant, the blocked experiments
waited out their retry backoff and the two cycles that followed did nothing).
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta
from typing import Literal

from pydantic import Field

from unbidden.contracts.common import Contract, utc_now
from unbidden.contracts.guardian import Mandate
from unbidden.contracts.jobs import JobStatus
from unbidden.store import Store

COLLECTION = "blocks"
PARKED = timedelta(days=30)  # a job waiting on a person: run again when released, or after this
Kind = Literal["pending_person", "compatibility", "missing_capability", "unavailable", "not_viable", "optional"]


class Block(Contract):
    id: str
    operation: str  # what stopped: "provision python dependencies for an experiment on opp_..."
    kind: Kind
    evidence: str  # the error or observation, excerpted
    needs: str  # the minimum that would unblock it, or why nothing a person grants would
    continues: str  # what runs again once it is given
    at: datetime = Field(default_factory=utc_now)
    resolved: bool = False
    waiting: list[str] = Field(default_factory=list[str])  # every operation held by this need
    jobs: list[str] = Field(default_factory=list[str])  # the queued jobs to run again once it is met
    resolved_at: datetime | None = None


# What happens to the job a block stopped, by kind (campaign 13, WS1): a person's need parks it until the answer;
# a service that did not answer is retried with backoff up to `UNAVAILABLE_ATTEMPTS`; what nobody can grant here
# (`compatibility`, `not_viable`) is declared at once, not retried at the same commit.
UNAVAILABLE_ATTEMPTS = 6
UNKNOWN = "nothing known a person can grant"
DECLARED = ("compatibility", "not_viable")


def attempts_for(block: Block, default: int) -> int:
    """How many attempts in all a job gets once `block` stopped it. An error nothing recognised (the fallback
    `compatibility`) keeps the usual retries: it may be passing."""
    if block.kind == "unavailable":
        return max(default, UNAVAILABLE_ATTEMPTS)
    if block.kind in DECLARED and not block.needs.startswith(UNKNOWN):
        return 0
    return default


def classify(operation: str, error: str, continues: str) -> Block:
    """A failure, read for what would unblock it."""
    text = error[-2000:]
    if "which the mandate's package registries do not list" in text:
        registries = re.findall(r"come from ([\w.\-, ]+), which the mandate", text)
        needed = registries[0].strip() if registries else "deb.debian.org"
        return _block(operation, "pending_person", text, f"add {needed} to egress.package_registries (system build "
                      "tools: a compiler and the C headers a package builds against)", continues)  # fmt: skip
    vcs = re.search(r"git\+https?://([\w.-]+)/", text)
    if vcs and re.search(r"Failed to (?:download|fetch|clone)|failed to build", text, re.I):
        # A dependency installed straight from a git repository (stage 9 evaluation, Prefect: `python-cli-bench @
        # git+https://github.com/...`): its host is what a person would allow, not something nobody can grant.
        return _block(operation, "pending_person", text, f"add {vcs.group(1)} to egress.package_registries (a "
                      "dependency is installed from a git repository there)", continues)  # fmt: skip
    if "sandbox.provision:" in text and "allowlist" in text:
        hosts = sorted(set(re.findall(r"destination ([\w.\-]+) is not in the mandate's allowlist", text)))
        needed = f"add {', '.join(hosts) or 'the package registry'} to egress.package_registries"
        return _block(operation, "pending_person", text, needed, continues)
    if re.search(r"needs a person's approval|approve-writes|awaiting approval", text):
        return _block(operation, "pending_person", text, "a person's approval (`unbidden approve-writes` or "
                      "`unbidden forge approve`), time-limited", continues)  # fmt: skip
    cap = re.search(r"remote spend this month is US\$[\d.]+, at the US\$([\d.]+) cap", text)
    if cap is not None:
        # The mandate's monthly cap, raised by a person or by the month turning (campaign 12, spoolman).
        return spend_block(operation, text, float(cap.group(1)), continues)
    if re.search(r"spend is split into envelopes|envelope '[\w.-]+' has|SpendRefused|machine's cap|verified balance",
                 text):  # fmt: skip
        return _block(operation, "pending_person", text, "spend authorized on this machine: `unbidden spend` (a "
                      "person's record of credits; never changed by the agent)", continues)  # fmt: skip
    if re.search(r"KillSwitchEngaged|kill switch (?:is )?engaged", text):
        return _block(operation, "pending_person", text, "the kill switch released: `unbidden resume`", continues)
    if re.search(r"ProviderUnauthorized|the key was refused|invalid_api_key", text):
        return _block(operation, "pending_person", text, "a Meta API key the service accepts: `unbidden key set` "
                      "replaces the refused one", continues)  # fmt: skip
    if re.search(r"refused the credential|401|403|not held by the broker", text):
        return _block(operation, "pending_person", text, "a credential that the service accepts, referenced in the "
                      "mandate's grant", continues)  # fmt: skip
    if re.search(r"still fail to build|Failed to build|no supported version|does not know a Debian package", text):
        return _block(operation, "compatibility", text, "nothing a person can grant: the project's dependencies do "
                      "not build here as declared (the cause is in the evidence)", continues)  # fmt: skip
    if re.search(r"no integration could be validated|no capability built", text):
        return _block(operation, "missing_capability", text, "an integration Unbidden could validate", continues)
    if re.search(r"Connection refused|timed out|unreachable|did not come up|503|502", text):
        return _block(operation, "unavailable", text, "the service to answer; retried later", continues)
    if re.search(r"no test|not collected|nothing to measure", text):
        return _block(operation, "not_viable", text, "nothing: the work cannot produce evidence here", continues)
    return _block(operation, "compatibility", text, f"{UNKNOWN}; the evidence says what failed", continues)


def _block(operation: str, kind: Kind, evidence: str, needs: str, continues: str) -> Block:
    # What a person grants is the same whatever it blocks; the other kinds stay one per operation.
    scope = "" if kind == "pending_person" else operation
    key = hashlib.sha256(f"{scope}|{kind}|{needs}".encode()).hexdigest()[:16]
    return Block(id=f"blk_{key}", operation=operation, kind=kind, evidence=evidence[-600:], needs=needs,
                 continues=continues, waiting=[operation])  # fmt: skip


def record(store: Store, block: Block, job: str | None = None) -> Block:
    """Kept once per need: the same need met again adds the operation and job it holds, not a new request."""
    existing = store.get(COLLECTION, block.id, Block)
    if existing is None or existing.resolved:
        existing = block
    for operation in block.waiting:
        if operation not in existing.waiting:
            existing.waiting.append(operation)
    if job is not None and job not in existing.jobs:
        existing.jobs.append(job)
    store.put(COLLECTION, existing)
    return existing


def spend_block(operation: str, evidence: str, cap_usd: float, continues: str) -> Block:
    """The mandate's monthly cap stopped a model call: a person raises it or the month ends (spoolman, campaign 12
    run 2: the cap was hit inside a measurement and nothing listed it as a block)."""
    return _block(operation, "pending_person", evidence,
                  f"raise business_constraints.maximum_monthly_spend_usd above US${cap_usd:.2f} in the mandate "
                  "(`unbidden setup budget`), or wait for next month", continues)  # fmt: skip


def met(block: Block, mandate: Mandate) -> bool:
    """Whether the mandate now shows a person's answer. Only what the mandate itself records can be checked here
    (registries, the monthly cap); an approval or a credential is seen when the work runs again, after its own
    backoff."""
    if block.kind != "pending_person":
        return False
    cap = re.match(r"raise business_constraints\.maximum_monthly_spend_usd above US\$([\d.]+)", block.needs)
    if cap is not None:
        return mandate.business_constraints.maximum_monthly_spend_usd > float(cap.group(1))
    asked = re.match(r"add ([\w.\-, ]+) to egress\.package_registries", block.needs)
    if asked is None:
        return False
    hosts = [h.strip() for h in asked.group(1).split(",") if h.strip()]
    return all(h in mandate.egress.package_registries for h in hosts)


def release(store: Store, mandate: Mandate) -> list[Block]:
    """Blocks whose need the mandate now meets: resolved, and the jobs they held queued to run now."""
    released = [b for b in open_blocks(store) if met(b, mandate)]
    for block in released:
        block.resolved, block.resolved_at = True, utc_now()
        store.put(COLLECTION, block)
        for held in store.jobs(status=JobStatus.QUEUED):
            if held.id in block.jobs:
                store.requeue(held)
    return released


def open_blocks(store: Store) -> list[Block]:
    return sorted((b for b in store.list(COLLECTION, Block) if not b.resolved), key=lambda b: b.at)
