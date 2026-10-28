"""Workspace configuration: providers, routing per tier and prices. Defaults target Meta models."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from unbidden.contracts.llm import Tier


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProviderConfig(_Config):
    kind: Literal["ollama", "openai_compat"]
    base_url: str
    key_env: str | None = None
    required_tool_choice: bool = True


class Route(_Config):
    provider: str
    model: str
    # Measured on Glimmer: "high" spends the whole budget thinking; "low" keeps tool calls valid.
    think: str | None = "low"
    think_schema_only: str | None = "low"
    think_budget: int = Field(default=1024, ge=0)
    max_tokens_cap: int = Field(default=16384, gt=0)


class Price(_Config):
    input_per_mtok: float = 0.0
    output_per_mtok: float = 0.0


class Prices(_Config):
    usd_per_local_compute_hour: float = 0.50
    models: dict[str, Price] = Field(default_factory=dict)


class BrainConfig(_Config):
    max_repairs: int = Field(default=1, ge=0)
    # `-contributor` models trade data-use terms for price; only a person turns them on.
    contributor_models: Literal["deny", "allow"] = "deny"


class Config(_Config):
    providers: dict[str, ProviderConfig]
    routing: dict[Tier, Route]
    prices: Prices = Field(default_factory=Prices)
    brain: BrainConfig = Field(default_factory=BrainConfig)


DEFAULTS: dict[str, Any] = {
    "providers": {
        "ollama": {"kind": "ollama", "base_url": "http://localhost:11434"},
        "meta": {
            "kind": "openai_compat",
            "base_url": "https://api.meta.ai/v1",
            "key_env": "MODEL_API_KEY",
            "required_tool_choice": False,
        },
    },
    "routing": {
        # "auto": the best Meta model this machine can run, among those installed (see brain/hardware.py).
        "local": {"provider": "ollama", "model": "auto"},
        "frontier": {"provider": "meta", "model": "muse-spark-1.3", "think_budget": 2048},
        # Muse Code is not offered to this account's key; Spark writes code until a benchmark says otherwise.
        "code": {"provider": "meta", "model": "muse-spark-1.3", "think_budget": 2048},
    },
    "prices": {
        "models": {
            "muse-spark-1.3": {"input_per_mtok": 1.25, "output_per_mtok": 4.25},
            # dev.meta.ai/docs/pricing-rate-limits, read 2026-10-28.
            "muse-wonder-1.0": {"input_per_mtok": 4.00, "output_per_mtok": 20.00},
        }
    },
}


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)  # pyright: ignore[reportUnknownArgumentType]
        else:
            out[key] = value
    return out


def load_config(path: Path | None = None) -> Config:
    data = DEFAULTS
    if path is not None and path.exists():
        raw = yaml.safe_load(path.read_text()) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"{path}: expected a mapping")
        data = _merge(DEFAULTS, raw)  # pyright: ignore[reportUnknownArgumentType]
    return Config.model_validate(data)
