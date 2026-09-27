from __future__ import annotations

from datetime import date, timedelta

from .schemas import Game, GameStatus

ESTIMATED_MAKEUP_DATE_METHOD = (
    "earliest_date_after_last_official_regular_season_game; one_game_per_team_per_day; KT-SS_pair_first"
)
CONTENDING_TEAMS = frozenset({"KT", "SS", "LG"})


def estimate_makeup_dates(games: list[Game]) -> list[Game]:
    postponed = [
        game
        for game in games
        if game.status is GameStatus.POSTPONED and game.game_date is None and game.estimated_game_date is None
    ]
    if not postponed:
        return games

    dated_remaining = [game.game_date for game in games if game.remaining and game.game_date is not None]
    if not dated_remaining:
        return games
    first_makeup_date = max(dated_remaining) + timedelta(days=1)
    occupied: dict[date, set[str]] = {}
    for game in games:
        if game.estimated_game_date is not None:
            occupied.setdefault(game.estimated_game_date, set()).update((game.away_team, game.home_team))

    estimates: dict[str, date] = {}
    prioritized = sorted(postponed, key=_makeup_priority)
    for game in prioritized:
        estimate = first_makeup_date
        while {game.away_team, game.home_team} & occupied.get(estimate, set()):
            estimate += timedelta(days=1)
        estimates[game.game_id] = estimate
        occupied.setdefault(estimate, set()).update((game.away_team, game.home_team))

    return [
        game.model_copy(update={"estimated_game_date": estimates[game.game_id]})
        if game.game_id in estimates
        else game
        for game in games
    ]


def _makeup_priority(game: Game) -> tuple[int, str]:
    teams = {game.away_team, game.home_team}
    priority = 0 if teams == {"KT", "SS"} else 1 if teams & CONTENDING_TEAMS else 2
    return priority, game.game_id
