from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Literal, Protocol

import httpx2
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ..config import EngineConfig
from ..features import GameFeatures
from ..network import create_client
from ..schemas import Game, JevStatus, validate_probability

JEV_COMPONENTS = ("starter", "offense", "bullpen", "fatigue", "matchup")
DEFAULT_JEV_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
DEFAULT_JEV_MODEL = "jev-latest"
JEV_COMPONENT_INSTRUCTIONS = {
    "starter": "Estimate the selected team's win probability from this game's starting pitchers and evidence status only.",
    "offense": "Estimate this game's win probability from batting lineups and status; do not invent missing players.",
    "bullpen": "Estimate this game's win probability from supplied bullpen evidence only; unavailable means no evidence.",
    "fatigue": "Estimate this game's win probability from schedule-derived rest and recent games; null means unavailable.",
    "matchup": "Estimate this game's win probability from the supplied matchup, never a season champion or final standings.",
}
HTTP_STATUS_MAP = {
    401: JevStatus.UNAUTHORIZED,
    403: JevStatus.FORBIDDEN,
    422: JevStatus.INVALID_REQUEST,
    429: JevStatus.RATE_LIMITED,
    529: JevStatus.OVERLOADED,
}


class JevJudgment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    probabilities: dict[str, float] = Field(default_factory=dict)
    status: JevStatus
    confidence: float | None = None
    message: str = ""
    request_hash: str | None = None
    model: str | None = None
    call_attempted: bool = False
    http_status_code: int | None = Field(default=None, ge=100, le=599)
    reason_code: Literal["missing_api_key", "missing_endpoint", "network_error", "invalid_response"] | None = None

    @field_validator("probabilities")
    @classmethod
    def validate_probabilities(cls, value: dict[str, float]) -> dict[str, float]:
        return {key: validate_probability(float(probability), f"jev.{key}") for key, probability in value.items()}

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, value: float | None) -> float | None:
        return None if value is None else validate_probability(value, "confidence")

    @property
    def probability(self) -> float | None:
        if not self.probabilities:
            return None
        return sum(self.probabilities.values()) / len(self.probabilities)


class JevAnswer(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: Literal["noul"]
    noul: float = Field(strict=True, ge=0.0, le=1.0)
    confidence: float | None = Field(default=None, strict=True, ge=0.0, le=1.0)


class JevResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str
    answers: dict[str, JevAnswer]


class JevClient(Protocol):
    def judge(self, game: Game, features: GameFeatures) -> JevJudgment: ...
    def smoke_test(self, game: Game, features: GameFeatures) -> JevJudgment: ...
    def close(self) -> None: ...


class HttpJevClient:
    def __init__(
        self,
        config: EngineConfig,
        client: httpx2.Client | None = None,
        env_file: Path | None = Path(".env"),
    ) -> None:
        self.config = config
        self._client = client or create_client(timeout_seconds=config.jev_timeout_seconds)
        self._owns_client = client is None
        resolved_env = env_file if env_file is None or env_file.is_absolute() else Path.cwd() / env_file
        if resolved_env is not None:
            load_dotenv(dotenv_path=resolved_env, override=False)
        self._api_key = os.getenv("TYPESAFE_API_KEY", "").strip()

    def smoke_test(self, game: Game, features: GameFeatures) -> JevJudgment:
        return self.judge(game, features)

    def judge(self, game: Game, features: GameFeatures) -> JevJudgment:
        endpoint = os.getenv("TYPESAFE_JEV_ENDPOINT") or self.config.jev_endpoint or DEFAULT_JEV_ENDPOINT
        model = os.getenv("TYPESAFE_JEV_MODEL") or self.config.jev_model or DEFAULT_JEV_MODEL
        payload = self._payload(game, features, model)
        request_hash = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if not self._api_key:
            return JevJudgment(
                status=JevStatus.UNAVAILABLE,
                message="TYPESAFE_API_KEY is not configured",
                reason_code="missing_api_key",
                request_hash=request_hash,
                model=model,
            )
        if not endpoint:
            return JevJudgment(
                status=JevStatus.UNAVAILABLE,
                message="TypeSafe endpoint is not configured",
                reason_code="missing_endpoint",
                request_hash=request_hash,
                model=model,
            )
        api_key = self._api_key.removeprefix("Bearer ").strip()
        try:
            response = self._client.post(
                endpoint,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
            )
        except (httpx2.TimeoutException, httpx2.NetworkError):
            return JevJudgment(
                status=JevStatus.UNAVAILABLE,
                message="TypeSafe network request failed",
                reason_code="network_error",
                request_hash=request_hash,
                model=model,
                call_attempted=True,
            )
        status = HTTP_STATUS_MAP.get(response.status_code, JevStatus.HTTP_ERROR)
        if response.status_code != 200:
            return JevJudgment(
                status=status,
                message=f"TypeSafe API returned HTTP {response.status_code}",
                request_hash=request_hash,
                model=model,
                call_attempted=True,
                http_status_code=response.status_code,
            )
        try:
            parsed = JevResponse.model_validate(response.json())
            missing = [component for component in JEV_COMPONENTS if component not in parsed.answers]
            if missing:
                raise ValueError("Required answer components are missing")
            probabilities = {component: parsed.answers[component].noul for component in JEV_COMPONENTS}
            confidences = [
                parsed.answers[component].confidence
                for component in JEV_COMPONENTS
                if parsed.answers[component].confidence is not None
            ]
        except (ValueError, TypeError, ValidationError):
            return JevJudgment(
                status=JevStatus.INVALID_RESPONSE,
                message="TypeSafe API returned invalid JSON or response schema",
                reason_code="invalid_response",
                request_hash=request_hash,
                model=model,
                call_attempted=True,
                http_status_code=200,
            )
        return JevJudgment(
            probabilities=probabilities,
            status=JevStatus.OK,
            confidence=sum(confidences) / len(confidences) if confidences else None,
            request_hash=request_hash,
            model=parsed.model,
            call_attempted=True,
            http_status_code=200,
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    @staticmethod
    def _payload(game: Game, features: GameFeatures, model: str) -> dict[str, object]:
        state = {
            "game_id": game.game_id,
            "analysis_as_of": game.as_of.isoformat(),
            "source_retrieved_at": game.retrieved_at.isoformat(),
            "team": features.team,
            "opponent": features.opponent,
            "is_home": features.is_home,
            "team_features": features.team_features.model_dump(),
            "opponent_features": features.opponent_features.model_dump(),
            "feature_quality": features.feature_quality,
            "feature_snapshot_hash": features.snapshot_hash,
            "game_evidence": {
                "away_starting_pitcher": game.away_starter.model_dump(mode="json"),
                "home_starting_pitcher": game.home_starter.model_dump(mode="json"),
                "away_lineup": game.away_lineup.model_dump(mode="json"),
                "home_lineup": game.home_lineup.model_dump(mode="json"),
                "schedule_fatigue": {
                    "target_game_date": game.simulation_date.isoformat() if game.simulation_date else None,
                    "target_game_date_status": game.simulation_date_status,
                    "away_rest_days": game.away_rest_days,
                    "home_rest_days": game.home_rest_days,
                    "away_games_last_7d": game.away_games_last_7d,
                    "home_games_last_7d": game.home_games_last_7d,
                    "status": "estimated" if game.simulation_date is not None else "unavailable",
                },
                "bullpen": {"status": "unavailable"},
            },
            "source": {
                "source_type": game.source_type.value,
                "source_uri": game.source_uri,
                "source_hash": game.source_hash,
            },
        }
        return {
            "state": state,
            "model": model,
            "questions": {
                component: {
                    "type": "noul",
                    "instructions": instructions,
                    "criteria": {"true": "The selected team wins the game.", "false": "The opponent wins the game."},
                }
                for component, instructions in JEV_COMPONENT_INSTRUCTIONS.items()
            },
        }


class MockJevClient:
    def __init__(self, judgments: dict[str, dict[str, float]]) -> None:
        self.judgments = judgments

    def smoke_test(self, game: Game, features: GameFeatures) -> JevJudgment:
        return self.judge(game, features)

    def judge(self, game: Game, features: GameFeatures) -> JevJudgment:
        values = self.judgments.get(game.game_id, {})
        if not values:
            return JevJudgment(status=JevStatus.UNAVAILABLE, message="mock judgment not configured")
        try:
            return JevJudgment(probabilities=values, status=JevStatus.OK)
        except ValueError as exc:
            return JevJudgment(status=JevStatus.INVALID_RESPONSE, message=str(exc))

    def close(self) -> None:
        return None
