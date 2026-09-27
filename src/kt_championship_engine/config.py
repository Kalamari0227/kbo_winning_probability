from __future__ import annotations

import tomllib
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EngineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    season: int = Field(default=2026, ge=1900)
    as_of: datetime
    simulations: int = Field(default=1_000_000, gt=0)
    seed: int = 20260920
    base_weight: float = Field(default=0.60, ge=0.0, le=1.0)
    jev_weight: float = Field(default=0.40, ge=0.0, le=1.0)
    tiebreak_policy: Literal["single_game"] = "single_game"
    allow_stale: bool = False
    jev_timeout_seconds: float = Field(default=10.0, gt=0.0)
    data_source: Literal["official", "local"] = "official"
    jev_endpoint: str | None = None
    jev_model: str | None = None

    @model_validator(mode="after")
    def weights_sum_to_one(self) -> EngineConfig:
        if abs((self.base_weight + self.jev_weight) - 1.0) > 1e-9:
            raise ValueError("base_weight + jev_weight must equal 1")
        return self

    @classmethod
    def from_toml(cls, path: Path, *, default_as_of: datetime | None = None) -> EngineConfig:
        with path.open("rb") as stream:
            values = tomllib.load(stream)
        if "as_of" not in values and default_as_of is not None:
            values["as_of"] = default_as_of
        return cls.model_validate(values)


def merge_config(config: EngineConfig, **overrides: object) -> EngineConfig:
    """Return a validated config with non-None CLI overrides applied."""

    values = config.model_dump()
    values.update({key: value for key, value in overrides.items() if value is not None})
    return EngineConfig.model_validate(values)
