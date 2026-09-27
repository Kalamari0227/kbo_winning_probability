from __future__ import annotations

import math

from ..schemas import Game, TeamFeatures, validate_probability


def base_win_probability(game: Game, features: dict[str, TeamFeatures]) -> float:
    """Return the home team's probability from the transparent v0.1 score."""

    home = features[game.home_team]
    away = features[game.away_team]
    score = 0.15
    score += 0.80 * (home.strength - away.strength)
    score += 0.35 * (home.recent_form - away.recent_form)
    score += 0.20 * (home.offense - away.offense)
    score += 0.20 * (home.defense - away.defense)
    score += 0.25 * (home.starter - away.starter)
    score += 0.20 * (home.bullpen - away.bullpen)
    score += 0.15 * (away.fatigue - home.fatigue)
    probability = 1.0 / (1.0 + math.exp(-score))
    return validate_probability(min(0.99, max(0.01, probability)), "base_probability")
