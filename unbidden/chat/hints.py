"""What to tell a person when the route refuses an analysis, and what would allow it. The reason is the router's
own; the hint names the command, never a change made for them."""

from __future__ import annotations

import re

HINTS: tuple[tuple[str, str], ...] = (
    (r"kill switch", "`unbidden resume` releases the kill switch"),
    (
        r"denies local inference",
        "`unbidden models local-first` allows the local model, or add the remote key with `unbidden key set`",
    ),
    (
        r"no remote model is configured|no MODEL_API_KEY|has no key",
        "add the key with `unbidden key set` (option api or mixed)",
    ),
    (r"profile local", "`unbidden models local-first` lets heavy work go to Meta's API"),
    (
        r"never leaves this machine",
        "the digest was labelled as data that never leaves; a local model (`unbidden models local-first`) can "
        "analyse it here",
    ),
    (
        r"leaves only renamed",
        "`unbidden models frontier --private-code allow` lets private code out un-renamed, or a local model "
        "analyses it here",
    ),
    (
        r"cap|spend|envelope|budget",
        "`unbidden spend` shows the cap; the mandate's maximum_monthly_spend_usd is this project's monthly cap",
    ),
    (r"egress|payload|destination", "`unbidden egress` shows the refusal and the payload"),
)


def hint_for(reason: str) -> str | None:
    for pattern, hint in HINTS:
        if re.search(pattern, reason):
            return hint
    return None
