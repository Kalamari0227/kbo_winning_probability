from __future__ import annotations

import hashlib
from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SourceType(StrEnum):
    OFFICIAL = "official"
    ESTIMATED = "estimated"
    MANUAL = "manual"
    STALE = "stale"


class EvidenceStatus(StrEnum):
    OFFICIAL = "official"
    ESTIMATED = "estimated"
    UNAVAILABLE = "unavailable"


class GameStatus(StrEnum):
    SCHEDULED = "scheduled"
    POSTPONED = "postponed"
    CANCELLED = "cancelled"
    FINAL = "final"


class JevStatus(StrEnum):
    OK = "ok"
    UNAVAILABLE = "unavailable"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    INVALID_REQUEST = "invalid_request"
    INVALID_RESPONSE = "invalid_response"
    RATE_LIMITED = "rate_limited"
    OVERLOADED = "overloaded"
    HTTP_ERROR = "http_error"
    DISABLED = "disabled"
    NOT_APPLICABLE = "not_applicable"
    SKIPPED = "skipped"


def validate_probability(value: float, field_name: str = "probability") -> float:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{field_name} must be between 0 and 1")
    return float(value)


class Provenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    as_of: datetime
    retrieved_at: datetime
    source_type: SourceType
    source_uri: str = ""
    source_hash: str = ""

    @model_validator(mode="after")
    def validate_temporal_order(self) -> Provenance:
        if self.as_of > self.retrieved_at:
            raise ValueError("as_of cannot be after retrieved_at")
        return self

    @field_validator("source_hash")
    @classmethod
    def hash_is_hex_or_empty(cls, value: str) -> str:
        if value and (len(value) != 64 or any(char not in "0123456789abcdef" for char in value.lower())):
            raise ValueError("source_hash must be a 64-character hexadecimal SHA-256")
        return value.lower()


class TeamStanding(Provenance):
    season: int
    team_id: str
    team_name: str
    played: int = Field(ge=0)
    wins: int = Field(ge=0)
    losses: int = Field(ge=0)
    ties: int = Field(ge=0)
    win_pct: float = Field(ge=0.0, le=1.0)
    rank: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_record(self) -> TeamStanding:
        if self.played != self.wins + self.losses + self.ties:
            raise ValueError("played must equal wins + losses + ties")
        denominator = self.wins + self.losses
        calculated = self.wins / denominator if denominator else 0.0
        if abs(self.win_pct - calculated) > 0.002:
            raise ValueError("win_pct does not match wins and losses")
        return self


class StartingPitcherEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    status: EvidenceStatus = EvidenceStatus.UNAVAILABLE
    source_game_id: str | None = None
    source_uri: str = ""
    source_hash: str = ""
    retrieved_at: datetime | None = None

    @model_validator(mode="after")
    def validate_status_and_name(self) -> StartingPitcherEvidence:
        if (self.status is EvidenceStatus.UNAVAILABLE and self.name is not None) or (
            self.status is not EvidenceStatus.UNAVAILABLE and not self.name
        ):
            raise ValueError("starting pitcher name must match its evidence status")
        return self


class LineupEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    players: list[str] = Field(default_factory=list)
    status: EvidenceStatus = EvidenceStatus.UNAVAILABLE
    source_game_id: str | None = None
    source_uri: str = ""
    source_hash: str = ""
    retrieved_at: datetime | None = None

    @model_validator(mode="after")
    def validate_status_and_players(self) -> LineupEvidence:
        if (self.status is EvidenceStatus.UNAVAILABLE and self.players) or (
            self.status is not EvidenceStatus.UNAVAILABLE and not self.players
        ):
            raise ValueError("lineup players must match their evidence status")
        return self


class Game(Provenance):
    model_config = ConfigDict(extra="forbid")

    game_id: str
    season: int
    game_date: date | None = None
    estimated_game_date: date | None = None
    status: GameStatus
    away_team: str
    home_team: str
    venue: str | None = None
    away_score: int | None = Field(default=None, ge=0)
    home_score: int | None = Field(default=None, ge=0)
    is_official_result: bool = False
    schedule_identity: Literal["verified", "inferred"] = "verified"
    away_starter: StartingPitcherEvidence = Field(default_factory=StartingPitcherEvidence)
    home_starter: StartingPitcherEvidence = Field(default_factory=StartingPitcherEvidence)
    away_lineup: LineupEvidence = Field(default_factory=LineupEvidence)
    home_lineup: LineupEvidence = Field(default_factory=LineupEvidence)
    away_rest_days: int | None = Field(default=None, ge=0)
    home_rest_days: int | None = Field(default=None, ge=0)
    away_games_last_7d: int | None = Field(default=None, ge=0)
    home_games_last_7d: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_final_score(self) -> Game:
        if self.game_date is not None and self.estimated_game_date is not None:
            raise ValueError("official and estimated game dates cannot both be set")
        if self.estimated_game_date is not None and self.status is not GameStatus.POSTPONED:
            raise ValueError("estimated game date is only valid for an undated postponement")
        if self.status is GameStatus.FINAL and (self.away_score is None or self.home_score is None):
            raise ValueError("final game requires both scores")
        if self.status is GameStatus.FINAL and self.game_date is None:
            raise ValueError("final game requires a game_date")
        if self.status is GameStatus.FINAL and not self.is_official_result:
            raise ValueError("final game must be marked as an official result")
        if self.status is not GameStatus.FINAL and (self.away_score is not None or self.home_score is not None):
            raise ValueError("non-final game cannot carry a score")
        if self.away_team == self.home_team:
            raise ValueError("away and home teams must differ")
        return self

    @property
    def remaining(self) -> bool:
        return self.status is not GameStatus.FINAL

    @property
    def simulation_date(self) -> date | None:
        return self.game_date or self.estimated_game_date

    @property
    def simulation_date_status(self) -> Literal["official", "estimated", "unavailable"]:
        if self.game_date is not None:
            return "official"
        if self.estimated_game_date is not None:
            return "estimated"
        return "unavailable"

    def is_head_to_head(self, team_a: str, team_b: str) -> bool:
        return {self.away_team, self.home_team} == {team_a, team_b}

    @property
    def official_evidence_count(self) -> int:
        return sum(
            status is EvidenceStatus.OFFICIAL
            for status in (
                self.away_starter.status,
                self.home_starter.status,
                self.away_lineup.status,
                self.home_lineup.status,
            )
        )

    @property
    def estimated_evidence_count(self) -> int:
        evidence_count = sum(
            status is EvidenceStatus.ESTIMATED
            for status in (
                self.away_starter.status,
                self.home_starter.status,
                self.away_lineup.status,
                self.home_lineup.status,
            )
        )
        return evidence_count + sum(
            metric is not None
            for metric in (
                self.away_rest_days,
                self.home_rest_days,
                self.away_games_last_7d,
                self.home_games_last_7d,
            )
        )


class TeamFeatures(BaseModel):
    model_config = ConfigDict(extra="forbid")

    team: str
    strength: float = 0.0
    recent_form: float = 0.0
    home_win_pct: float = 0.5
    away_win_pct: float = 0.5
    offense: float = 0.0
    defense: float = 0.0
    bullpen: float = 0.0
    starter: float = 0.0
    fatigue: float = 0.0
    feature_quality: Literal["official", "estimated", "mixed"] = "estimated"


class GameForecast(BaseModel):
    model_config = ConfigDict(extra="forbid")

    game_id: str
    team: str
    opponent: str
    is_home: bool = False
    game_date: date | None = None
    estimated_game_date: date | None = None
    is_remaining: bool = True
    base_probability: float | None = None
    jev_probability: float | None = None
    combined_probability: float | None = None
    jev_status: JevStatus = JevStatus.UNAVAILABLE
    jev_call_attempted: bool = False
    jev_http_status: int | None = Field(default=None, ge=100, le=599)
    jev_reason_code: str | None = None
    jev_is_preflight: bool = False
    jev_components: dict[str, float] = Field(default_factory=dict)
    jev_confidence: float | None = None
    jev_message: str | None = None
    jev_request_hash: str | None = None
    jev_model: str | None = None
    effective_base_weight: float | None = Field(default=None, ge=0.0, le=1.0)
    effective_jev_weight: float | None = Field(default=None, ge=0.0, le=1.0)
    feature_quality: Literal["official", "estimated", "mixed"] = "estimated"
    actual_result: Literal["win", "loss", "tie"] | None = None
    result_source: SourceType | None = None
    feature_snapshot_hash: str = ""
    predicted_at: datetime | None = None

    @field_validator("base_probability", "jev_probability", "combined_probability")
    @classmethod
    def probabilities_are_valid(cls, value: float | None, info) -> float | None:
        if value is None:
            return None
        return validate_probability(value, info.field_name)

    @field_validator("jev_components")
    @classmethod
    def component_probabilities_are_valid(cls, value: dict[str, float]) -> dict[str, float]:
        return {key: validate_probability(float(probability), f"jev.{key}") for key, probability in value.items()}

    @field_validator("jev_confidence")
    @classmethod
    def confidence_is_valid(cls, value: float | None) -> float | None:
        return None if value is None else validate_probability(value, "jev_confidence")

    @field_validator("feature_snapshot_hash")
    @classmethod
    def feature_hash_is_valid(cls, value: str) -> str:
        if value and (len(value) != 64 or any(char not in "0123456789abcdef" for char in value.lower())):
            raise ValueError("feature_snapshot_hash must be a 64-character hexadecimal SHA-256")
        return value.lower()

    @field_validator("jev_request_hash")
    @classmethod
    def request_hash_is_valid(cls, value: str | None) -> str | None:
        if value and (len(value) != 64 or any(char not in "0123456789abcdef" for char in value.lower())):
            raise ValueError("jev_request_hash must be a 64-character hexadecimal SHA-256")
        return value.lower() if value else value


class DataManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    season: int
    as_of: datetime
    as_of_precision: Literal["date", "datetime"] = "datetime"
    retrieved_at: datetime
    source_type: SourceType
    source_uris: list[str] = Field(default_factory=list)
    source_hashes: list[str] = Field(default_factory=list)
    stale: bool = False
    warnings: list[str] = Field(default_factory=list)
    official_record_count: int | None = Field(default=None, ge=0)
    estimated_record_count: int | None = Field(default=None, ge=0)
    inferred_schedule_record_count: int | None = Field(default=None, ge=0)
    estimated_schedule_method: str | None = None

    @model_validator(mode="after")
    def validate_temporal_order(self) -> DataManifest:
        if self.as_of > self.retrieved_at:
            raise ValueError("manifest as_of cannot be after retrieved_at")
        return self


class Snapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    season: int
    standings: list[TeamStanding]
    games: list[Game]
    manifest: DataManifest


def feature_hash(features: dict[str, object]) -> str:
    payload = repr(sorted(features.items())).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
