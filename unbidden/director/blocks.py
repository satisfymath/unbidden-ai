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
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Literal

from pydantic import Field

from unbidden.contracts.common import Contract, utc_now
from unbidden.store import Store

COLLECTION = "blocks"
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


def classify(operation: str, error: str, continues: str) -> Block:
    """A failure, read for what would unblock it."""
    text = error[-2000:]
    if "which the mandate's package registries do not list" in text:
        registries = re.findall(r"come from ([\w.\-, ]+), which the mandate", text)
        needed = registries[0].strip() if registries else "deb.debian.org"
        return _block(operation, "pending_person", text, f"add {needed} to egress.package_registries (system build "
                      "tools: a compiler and the C headers a package builds against)", continues)  # fmt: skip
    if "sandbox.provision:" in text and "allowlist" in text:
        hosts = sorted(set(re.findall(r"destination ([\w.\-]+) is not in the mandate's allowlist", text)))
        needed = f"add {', '.join(hosts) or 'the package registry'} to egress.package_registries"
        return _block(operation, "pending_person", text, needed, continues)
    if re.search(r"needs a person's approval|approve-writes|awaiting approval", text):
        return _block(operation, "pending_person", text, "a person's approval (`unbidden approve-writes` or "
                      "`unbidden forge approve`), time-limited", continues)  # fmt: skip
    if re.search(r"refused the credential|401|403|invalid_api_key|not held by the broker", text):
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
    return _block(operation, "compatibility", text, "nothing known a person can grant; the evidence says what failed",
                  continues)  # fmt: skip


def _block(operation: str, kind: Kind, evidence: str, needs: str, continues: str) -> Block:
    key = hashlib.sha256(f"{operation}|{kind}|{needs}".encode()).hexdigest()[:16]
    return Block(id=f"blk_{key}", operation=operation, kind=kind, evidence=evidence[-600:], needs=needs,
                 continues=continues)  # fmt: skip


def record(store: Store, block: Block) -> Block:
    """Kept once per (operation, kind, need): the same block seen again is not a new request."""
    existing = store.get(COLLECTION, block.id, Block)
    if existing is not None and not existing.resolved:
        return existing
    store.put(COLLECTION, block)
    return block


def open_blocks(store: Store) -> list[Block]:
    return sorted((b for b in store.list(COLLECTION, Block) if not b.resolved), key=lambda b: b.at)
