from __future__ import annotations

from pathlib import Path

import yaml

from unbidden.contracts.guardian import Mandate


def load_mandate(path: Path) -> Mandate:
    raw: object = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict) or "mandate" not in raw:
        raise ValueError(f"{path}: expected a top-level 'mandate' mapping")
    return Mandate.model_validate(raw["mandate"])
