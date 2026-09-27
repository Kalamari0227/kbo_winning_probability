from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..config import EngineConfig
from ..schemas import JevStatus, validate_probability


class CombinedProbability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: float
    jev_probability: float | None = None
    jev_status: JevStatus
    effective_base_weight: float = Field(ge=0.0, le=1.0)
    effective_jev_weight: float = Field(ge=0.0, le=1.0)

    @field_validator("value", "jev_probability")
    @classmethod
    def probabilities_are_valid(cls, value: float | None, info) -> float | None:
        return None if value is None else validate_probability(value, info.field_name)


def combine_probabilities(
    base: float,
    jev: float | None,
    config: EngineConfig,
    *,
    jev_status: JevStatus | None = None,
) -> CombinedProbability:
    base = validate_probability(base, "base_probability")
    if jev is None:
        return CombinedProbability(
            value=_clip_probability(base),
            jev_probability=None,
            jev_status=jev_status or JevStatus.UNAVAILABLE,
            effective_base_weight=1.0,
            effective_jev_weight=0.0,
        )
    jev = validate_probability(jev, "jev_probability")
    return CombinedProbability(
        value=_clip_probability(config.base_weight * base + config.jev_weight * jev),
        jev_probability=jev,
        jev_status=JevStatus.OK,
        effective_base_weight=config.base_weight,
        effective_jev_weight=config.jev_weight,
    )


def _clip_probability(value: float) -> float:
    return max(0.01, min(0.99, float(value)))
