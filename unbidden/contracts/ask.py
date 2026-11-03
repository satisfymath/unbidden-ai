"""A question for the person, as a record: what the agent needs, the ways out it offers, and the answer.

Every place the agent stops for a person (a proposal waiting for approval, a key the service refused, a hold after
a bad deploy, a deploy procedure found in the repository, a registry the sandbox needs, a capability built and
waiting) becomes one open ask, deduplicated by subject, with options a person picks from the app, the dashboard or
`unbidden ask`. Answering applies the same effect the CLI command would; nothing else reads the answer."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from unbidden.contracts.common import Contract, new_id, utc_now

Kind = Literal[
    "approval", "credential", "access", "hold", "deploy_steps", "spend", "capability", "registry", "drill", "resume",
    "ledger", "connection",
]  # fmt: skip
Status = Literal["open", "answered", "withdrawn"]
Input = Literal["none", "secret", "text"]


class AskOption(Contract):
    key: str
    label: str  # "approve: the pull request opens on the next cycle"
    input: Input = "none"  # the option needs a value typed with it (a key, an amount)


class Ask(Contract):
    id: str = Field(default_factory=lambda: new_id("ask"))
    kind: Kind
    title: str  # one line: what is asked
    why: str  # what the agent found, and what the answer changes
    options: list[AskOption]
    default: str | None = None
    status: Status = "open"
    subject: str | None = None  # the record it is about: an opportunity, a hold, a block, a need, an action
    correlation_id: str | None = None
    dedup_key: str  # one open ask per subject
    cli: str | None = None  # the command that answers it outside the app
    created_at: datetime = Field(default_factory=utc_now)
    answer: str | None = None
    answered_by: str | None = None
    answered_at: datetime | None = None
    outcome: str | None = None  # what applying the answer did, in one line
    withdrawn_why: str | None = None  # resolved another way (approved from the CLI, the hold released)

    def option(self, key: str) -> AskOption | None:
        return next((o for o in self.options if o.key == key), None)

    def as_summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "why": self.why,
            "options": [o.model_dump() for o in self.options],
            "default": self.default,
            "status": self.status,
            "subject": self.subject,
            "cli": self.cli,
            "created_at": self.created_at.isoformat(),
            "answer": self.answer,
            "outcome": self.outcome,
        }
