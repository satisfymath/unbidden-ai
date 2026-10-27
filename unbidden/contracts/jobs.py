from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from unbidden.contracts.common import Contract, new_id, utc_now


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class Job(Contract):
    id: str = Field(default_factory=lambda: new_id("job"))
    type: str = Field(pattern=r"^[a-z][a-z0-9_.]*$")
    payload: dict[str, Any] = Field(default_factory=dict)
    status: JobStatus = JobStatus.QUEUED
    priority: int = 100
    attempts: int = 0
    max_attempts: int = 3
    run_at: datetime = Field(default_factory=utc_now)
    idempotency_key: str
    correlation_id: str | None = None
    last_error: str | None = None
