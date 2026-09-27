from __future__ import annotations

from datetime import UTC, datetime

from .config import EngineConfig
from .features import GameFeatures
from .models.base import base_win_probability
from .models.combine import combine_probabilities
from .models.jev import HttpJevClient, JevJudgment
from .schemas import Game, GameForecast, GameStatus, JevStatus, Snapshot, TeamFeatures


def build_forecasts(
    snapshot: Snapshot,
    features: dict[str, TeamFeatures],
    config: EngineConfig,
    *,
    no_jev: bool,
) -> list[GameForecast]:
    pending = [game for game in snapshot.games if game.remaining]
    jev_client = HttpJevClient(config) if pending and not no_jev else None
    preflight_game = pending[0] if pending and not no_jev else None
    preflight_features = GameFeatures.from_game(preflight_game, features) if preflight_game is not None else None
    preflight = (
        jev_client.smoke_test(preflight_game, preflight_features)
        if jev_client is not None and preflight_game is not None and preflight_features is not None
        else None
    )
    jev_available = preflight is not None and preflight.status is JevStatus.OK
    halted = False
    forecasts: list[GameForecast] = []
    try:
        for game in snapshot.games:
            if game.status is GameStatus.FINAL:
                forecasts.append(_actual_result(game, features))
                continue
            game_features = GameFeatures.from_game(game, features)
            base = base_win_probability(game, features)
            is_preflight = game is preflight_game
            if no_jev:
                judgment = JevJudgment(status=JevStatus.DISABLED)
            elif is_preflight:
                judgment = preflight or JevJudgment(status=JevStatus.SKIPPED)
            elif not jev_available or halted:
                judgment = JevJudgment(status=JevStatus.SKIPPED, message="Jev calls stopped after preflight failure")
            else:
                judgment = jev_client.judge(game, game_features) if jev_client is not None else JevJudgment(
                    status=JevStatus.SKIPPED
                )
                if judgment.status is not JevStatus.OK:
                    halted = True
            combined = combine_probabilities(
                base,
                judgment.probability if judgment.status is JevStatus.OK else None,
                config,
                jev_status=judgment.status,
            )
            forecasts.append(
                GameForecast(
                    game_id=game.game_id,
                    team=game.home_team,
                    opponent=game.away_team,
                    is_home=True,
                    game_date=game.game_date,
                    estimated_game_date=game.estimated_game_date,
                    is_remaining=True,
                    base_probability=base,
                    jev_probability=judgment.probability if judgment.status is JevStatus.OK else None,
                    combined_probability=combined.value,
                    jev_status=judgment.status,
                    jev_call_attempted=judgment.call_attempted,
                    jev_http_status=judgment.http_status_code,
                    jev_reason_code=judgment.reason_code,
                    jev_is_preflight=is_preflight,
                    jev_components=judgment.probabilities,
                    jev_confidence=judgment.confidence,
                    jev_message=judgment.message or None,
                    jev_request_hash=judgment.request_hash,
                    jev_model=judgment.model,
                    effective_base_weight=combined.effective_base_weight,
                    effective_jev_weight=combined.effective_jev_weight,
                    feature_quality=game_features.feature_quality,
                    feature_snapshot_hash=game_features.snapshot_hash,
                    predicted_at=datetime.now(UTC),
                )
            )
    finally:
        if jev_client is not None:
            jev_client.close()
    return forecasts


def _actual_result(game: Game, features: dict[str, TeamFeatures]) -> GameForecast:
    if game.away_score is None or game.home_score is None:
        raise ValueError(f"final game {game.game_id} has no official score")
    result = "tie" if game.away_score == game.home_score else "win" if game.home_score > game.away_score else "loss"
    return GameForecast(
        game_id=game.game_id,
        team=game.home_team,
        opponent=game.away_team,
        is_home=True,
        game_date=game.game_date,
        estimated_game_date=game.estimated_game_date,
        is_remaining=False,
        jev_status=JevStatus.NOT_APPLICABLE,
        feature_quality=features[game.home_team].feature_quality,
        actual_result=result,
        result_source=game.source_type,
    )
