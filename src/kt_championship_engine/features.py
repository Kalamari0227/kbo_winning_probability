from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict

from .schemas import Game, Snapshot, TeamFeatures, feature_hash


class GameFeatures(BaseModel):
    model_config = ConfigDict(extra="forbid")

    game_id: str
    team: str
    opponent: str
    is_home: bool
    team_features: TeamFeatures
    opponent_features: TeamFeatures
    feature_quality: str
    snapshot_hash: str = ""

    @classmethod
    def from_game(cls, game: Game, features: dict[str, TeamFeatures], team: str | None = None) -> GameFeatures:
        selected_team = team or game.home_team
        opponent = game.away_team if selected_team == game.home_team else game.home_team
        team_features = features[selected_team]
        opponent_features = features[opponent]
        snapshot_hash = feature_hash(
            {
                "game_id": game.game_id,
                "team": selected_team,
                "opponent": opponent,
                "team_features": team_features.model_dump(),
                "opponent_features": opponent_features.model_dump(),
                "game_evidence": {
                    "game_date": game.game_date,
                    "estimated_game_date": game.estimated_game_date,
                    "away_starter": game.away_starter.model_dump(mode="json"),
                    "home_starter": game.home_starter.model_dump(mode="json"),
                    "away_lineup": game.away_lineup.model_dump(mode="json"),
                    "home_lineup": game.home_lineup.model_dump(mode="json"),
                    "away_rest_days": game.away_rest_days,
                    "home_rest_days": game.home_rest_days,
                    "away_games_last_7d": game.away_games_last_7d,
                    "home_games_last_7d": game.home_games_last_7d,
                },
            }
        )
        quality = "official" if team_features.feature_quality == opponent_features.feature_quality == "official" else "mixed"
        return cls(
            game_id=game.game_id,
            team=selected_team,
            opponent=opponent,
            is_home=selected_team == game.home_team,
            team_features=team_features,
            opponent_features=opponent_features,
            feature_quality=quality,
            snapshot_hash=snapshot_hash,
        )


def build_team_features(snapshot: Snapshot) -> dict[str, TeamFeatures]:
    standings = {standing.team_id: standing for standing in snapshot.standings}
    features: dict[str, TeamFeatures] = {}
    for team_id, standing in standings.items():
        final_games = [game for game in snapshot.games if not game.remaining and team_id in {game.away_team, game.home_team}]
        final_games.sort(key=lambda game: game.game_date or date.min)
        recent_games = final_games[-10:]
        recent_wins = sum(
            1
            for game in recent_games
            if (game.home_team == team_id and game.home_score > game.away_score)
            or (game.away_team == team_id and game.away_score > game.home_score)
        )
        recent_decisions = sum(1 for game in recent_games if game.home_score != game.away_score)
        recent_form = recent_wins / recent_decisions if recent_decisions else standing.win_pct

        home_games = [game for game in final_games if game.home_team == team_id]
        away_games = [game for game in final_games if game.away_team == team_id]
        home_win_pct = _win_pct(home_games, team_id, fallback=standing.win_pct)
        away_win_pct = _win_pct(away_games, team_id, fallback=standing.win_pct)
        strength = (standing.win_pct - 0.5) * 2.0
        # Standings and completed scores may be official, but starter/bullpen/
        # fatigue inputs and the derived strength proxies are model estimates.
        source_type = "mixed" if standing.source_type.value == "official" else "estimated"
        features[team_id] = TeamFeatures(
            team=team_id,
            strength=strength,
            recent_form=recent_form,
            home_win_pct=home_win_pct,
            away_win_pct=away_win_pct,
            offense=strength,
            defense=strength,
            feature_quality=source_type,
        )
    return features


def _win_pct(games: list[Game], team_id: str, fallback: float) -> float:
    decisions = 0
    wins = 0
    for game in games:
        if game.home_score == game.away_score:
            continue
        decisions += 1
        if (game.home_team == team_id and game.home_score > game.away_score) or (
            game.away_team == team_id and game.away_score > game.home_score
        ):
            wins += 1
    return wins / decisions if decisions else fallback
