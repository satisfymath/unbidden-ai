from __future__ import annotations

from pathlib import Path


class KillSwitch:
    """A file anyone can create by hand. While it exists, no job starts and no model is called."""

    def __init__(self, state_dir: Path) -> None:
        self.path = state_dir / "KILL"

    @property
    def engaged(self) -> bool:
        return self.path.exists()

    def engage(self, reason: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(reason.strip() + "\n")

    def release(self) -> None:
        self.path.unlink(missing_ok=True)
