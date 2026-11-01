"""The egress gate: pure judgement of what may leave this machine. Recording happens in the store."""

from __future__ import annotations

import hashlib

from unbidden.contracts.guardian import EgressKind, EgressVerdict, Mandate
from unbidden.guardian.credentials import broker
from unbidden.guardian.policy import GITHUB_HOSTS
from unbidden.guardian.scanner import SensitiveTermIndex, scan, secret_hits


def _verdict(kind: EgressKind, destination: str, payload: str, reasons: list[str], matched: list[str]) -> EgressVerdict:
    leaked = broker().leaked(payload)
    if leaked:
        # A held credential's exact value, whatever pattern scanners would make of it, never leaves.
        reasons = [*reasons, f"payload contains the value of held credential(s): {', '.join(leaked)}"]
        matched = [*matched, *(f"credential:{name}" for name in leaked)]
    data = payload.encode()
    return EgressVerdict(
        allowed=not reasons,
        kind=kind,
        destination=destination,
        reasons=reasons,
        matched=sorted(set(matched)),
        payload_sha256=hashlib.sha256(data).hexdigest(),
        payload_bytes=len(data),
    )


def evaluate_synthetic(
    mandate: Mandate, destination: str, payload: str, identifiers: SensitiveTermIndex
) -> EgressVerdict:
    """A task for a remote model must be synthetic: no secrets and no identifier of the real environment."""
    policy = mandate.egress.remote_models
    reasons: list[str] = []
    if destination not in policy.destinations:
        reasons.append(f"{destination} is not an allowed remote model destination")
    size = len(payload.encode())
    if size > policy.max_payload_bytes:
        reasons.append(f"payload is {size} bytes, above the {policy.max_payload_bytes}-byte cap")
    hits = scan(payload, identifiers)
    secrets = secret_hits(hits)
    if secrets:
        reasons.append(f"payload contains {len(secrets)} secret(s)")
    real = [h for h in hits if h.kind.startswith("identifier:")]
    if real:
        reasons.append(f"payload names {len({h.kind for h in real})} real identifier(s) of this environment")
    return _verdict("synthetic_task", destination, payload, reasons, [h.kind for h in hits])


def evaluate_github(mandate: Mandate, destination: str, payload: str) -> EgressVerdict:
    """A pull request must name the repository's own code, so only secrets and size are checked."""
    policy = mandate.egress.github
    reasons: list[str] = []
    if policy.repository is None or destination not in GITHUB_HOSTS:
        reasons.append(f"{destination} is not an allowed GitHub destination for this workspace")
    size = len(payload.encode())
    if size > policy.max_payload_bytes:
        reasons.append(f"payload is {size} bytes, above the {policy.max_payload_bytes}-byte cap")
    secrets = secret_hits(scan(payload))
    if secrets:
        reasons.append(f"payload contains {len(secrets)} secret(s)")
    return _verdict("github", destination, payload, reasons, [h.kind for h in secrets])


def evaluate_screenshots(mandate: Mandate, destination: str, images: list[bytes], text: str) -> EgressVerdict:
    """Screenshots leave only where a person allowed it for this workspace; the text sent with them is still scanned
    for secrets. The verdict carries the images' total size and a digest of all of them, never their content."""
    reasons: list[str] = []
    if mandate.models.screenshots_to_frontier != "allow":
        reasons.append("this workspace's mandate does not allow screenshots to leave (models.screenshots_to_frontier)")
    if destination not in mandate.egress.remote_models.destinations:
        reasons.append(f"{destination} is not an allowed remote model destination")
    secrets = secret_hits(scan(text))
    if secrets:
        reasons.append(f"the text sent with the images contains {len(secrets)} secret(s)")
    if broker().leaked(text):
        reasons.append("the text sent with the images contains a held credential's value")
    digest = hashlib.sha256(b"".join(images) + text.encode()).hexdigest()
    return EgressVerdict(
        allowed=not reasons,
        kind="screenshots",
        destination=destination,
        reasons=reasons,
        matched=[h.kind for h in secrets],
        payload_sha256=digest,
        payload_bytes=sum(len(i) for i in images) + len(text.encode()),
    )
