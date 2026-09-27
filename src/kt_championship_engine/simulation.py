from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np

from .schemas import Game, GameForecast, Snapshot, TeamStanding, validate_probability


@dataclass(frozen=True)
class FinalStanding:
    team: str
    wins: int
    losses: int
    ties: int = 0

    @property
    def win_pct(self) -> float:
        decisions = self.wins + self.losses
        return self.wins / decisions if decisions else 0.0


@dataclass(frozen=True)
class FirstPlaceResult:
    winner: str | None
    leaders: tuple[str, ...]
    kt_first_place_count: int
    ss_first_place_count: int
    co_champion_count: int
    tiebreak_resolved_count: int
    unresolved_count: int = 0


@dataclass(frozen=True)
class MagicNumber:
    wins_needed: int | None
    strict_wins_needed: int | None
    competitor: str | None
    combined_magic_number: int | None = None
    combined_tie_number: int | None = None
    kt_current_wins: int | None = None
    competitor_current_losses: int | None = None
    ss_current_losses: int | None = None
    season_games: int | None = None


@dataclass(frozen=True)
class DateConfirmation:
    date: date
    probability: float
    count: int


@dataclass(frozen=True)
class DateSimulationResult:
    first_confirmation_dates: Sequence[date | None]


@dataclass
class SimulationResult:
    simulations: int
    seed: int
    team_win_totals: dict[str, np.ndarray]
    team_loss_totals: dict[str, np.ndarray]
    team_tie_totals: dict[str, np.ndarray]
    first_place_counts: dict[str, int]
    rank_counts: dict[str, dict[int, float]]
    co_champion_count: int
    tiebreak_resolved_count: int
    unresolved_first_place_count: int
    linked_game_sample_count: int
    first_confirmation_dates: list[date | None]
    kt_won_unknown_confirmation_count: int = 0

    @property
    def kt_first_place_probability(self) -> float:
        return self.first_place_counts.get("KT", 0) / self.simulations

    @property
    def ss_first_place_probability(self) -> float:
        return self.first_place_counts.get("SS", 0) / self.simulations

    def rank_probability(self, team: str, rank: int) -> float:
        return self.rank_counts.get(team, {}).get(rank, 0.0) / self.simulations

    def top_three_probability(self, team: str) -> float:
        return sum(self.rank_probability(team, rank) for rank in (1, 2, 3))

    def as_date_result(self) -> DateSimulationResult:
        return DateSimulationResult(self.first_confirmation_dates)


def simulate(
    snapshot: Snapshot,
    forecasts: list[GameForecast],
    simulations: int,
    seed: int,
) -> SimulationResult:
    if simulations <= 0:
        raise ValueError("simulations must be positive")
    forecast_by_game = {forecast.game_id: forecast for forecast in forecasts}
    remaining_games = sorted(
        (game for game in snapshot.games if game.remaining),
        key=lambda game: (game.simulation_date is None, game.simulation_date or date.max, game.game_id),
    )
    missing = [game.game_id for game in remaining_games if game.game_id not in forecast_by_game]
    if missing:
        raise ValueError(f"missing forecasts for games: {', '.join(missing)}")

    team_ids = [standing.team_id for standing in snapshot.standings]
    standing_by_team = {standing.team_id: standing for standing in snapshot.standings}
    wins = {team: np.full(simulations, standing_by_team[team].wins, dtype=np.int16) for team in team_ids}
    losses = {team: np.full(simulations, standing_by_team[team].losses, dtype=np.int16) for team in team_ids}
    ties = {team: np.full(simulations, standing_by_team[team].ties, dtype=np.int16) for team in team_ids}
    rng = np.random.default_rng(seed)
    first_confirmation_dates: list[date | None] = [None] * simulations
    linked_game_ids = {game.game_id for game in remaining_games if game.is_head_to_head("KT", "SS")}

    batch_start = 0
    while batch_start < len(remaining_games):
        game_date = remaining_games[batch_start].simulation_date
        batch_end = batch_start
        while batch_end < len(remaining_games) and remaining_games[batch_end].simulation_date == game_date:
            batch_end += 1
        for game in remaining_games[batch_start:batch_end]:
            forecast = forecast_by_game[game.game_id]
            probability = forecast.combined_probability
            if probability is None:
                probability = forecast.base_probability
            if probability is None:
                raise ValueError(f"missing probability for remaining game {game.game_id}")
            probability = validate_probability(probability, f"forecast.{game.game_id}")
            if forecast.team == game.home_team:
                home_probability = probability
            elif forecast.team == game.away_team:
                home_probability = 1.0 - probability
            else:
                raise ValueError(f"forecast team is not a participant in {game.game_id}")
            home_probability = validate_probability(home_probability, f"home_probability.{game.game_id}")
            home_wins = rng.random(simulations) < home_probability
            wins[game.home_team] += home_wins
            losses[game.away_team] += home_wins
            wins[game.away_team] += ~home_wins
            losses[game.home_team] += ~home_wins
        if game_date is not None:
            remaining_after = _remaining_counts_after_date(remaining_games, game_date)
            safe = _kt_is_safe(wins, losses, remaining_after, simulations)
            for index in np.flatnonzero(safe):
                if first_confirmation_dates[index] is None:
                    first_confirmation_dates[index] = game_date
        batch_start = batch_end

    (
        first_place_counts,
        rank_counts,
        co_champion_count,
        tiebreak_resolved_count,
        unresolved_count,
        kt_winner_mask,
    ) = (
        _resolve_first_place_batch(
            wins,
            losses,
            team_ids,
            tiebreak_probability=_head_to_head_tiebreak_probability(forecasts, snapshot),
            rng=rng,
        )
    )
    unknown_confirmation_mask = np.fromiter(
        (confirmation_date is None for confirmation_date in first_confirmation_dates),
        dtype=bool,
        count=simulations,
    )
    kt_won_unknown_confirmation_count = int(np.count_nonzero(kt_winner_mask & unknown_confirmation_mask))

    return SimulationResult(
        simulations=simulations,
        seed=seed,
        team_win_totals=wins,
        team_loss_totals=losses,
        team_tie_totals=ties,
        first_place_counts=first_place_counts,
        rank_counts=rank_counts,
        co_champion_count=co_champion_count,
        tiebreak_resolved_count=tiebreak_resolved_count,
        unresolved_first_place_count=unresolved_count,
        linked_game_sample_count=len(linked_game_ids),
        first_confirmation_dates=first_confirmation_dates,
        kt_won_unknown_confirmation_count=kt_won_unknown_confirmation_count,
    )


def _resolve_first_place_batch(
    wins: dict[str, np.ndarray],
    losses: dict[str, np.ndarray],
    team_ids: list[str],
    *,
    tiebreak_probability: float,
    rng: np.random.Generator,
) -> tuple[dict[str, int], dict[str, dict[int, float]], int, int, int, np.ndarray]:
    """Resolve all Monte Carlo standings in vectorized NumPy operations."""

    probability = validate_probability(tiebreak_probability, "tiebreak_probability")
    simulations = len(next(iter(wins.values())))
    best_pct = np.full(simulations, -np.inf, dtype=float)
    leader_count = np.zeros(simulations, dtype=np.int8)
    percentages: dict[str, np.ndarray] = {}
    for team in team_ids:
        decisions = wins[team] + losses[team]
        pct = np.divide(wins[team], decisions, out=np.zeros(simulations, dtype=float), where=decisions != 0)
        percentages[team] = pct
        better = pct > best_pct + 1e-12
        equal = np.abs(pct - best_pct) <= 1e-12
        leader_count[better] = 1
        leader_count[equal & ~better] += 1
        best_pct[better] = pct[better]

    rank_counts = _compute_rank_counts_from_percentages(percentages, team_ids)
    leader_masks = {team: np.abs(percentages[team] - best_pct) <= 1e-12 for team in team_ids}
    first_place_counts = {
        team: int(np.count_nonzero(leader_masks[team] & (leader_count == 1))) for team in team_ids
    }
    kt_winner_mask = leader_masks.get("KT", np.zeros(simulations, dtype=bool)) & (leader_count == 1)
    kt_ss_tie = (
        leader_masks.get("KT", np.zeros(simulations, dtype=bool))
        & leader_masks.get("SS", np.zeros(simulations, dtype=bool))
        & (leader_count == 2)
    )
    tiebreak_count = int(np.count_nonzero(kt_ss_tie))
    tiebreak_indices = np.flatnonzero(kt_ss_tie)
    tiebreak_winners = rng.random(tiebreak_count) < probability if tiebreak_count else np.array([], dtype=bool)
    kt_winner_mask[tiebreak_indices] = tiebreak_winners
    tiebreak_kt = int(np.count_nonzero(tiebreak_winners))
    tiebreak_ss = tiebreak_count - tiebreak_kt
    if tiebreak_count:
        tiebreak_bias = 0.5 * (tiebreak_kt - tiebreak_ss)
        rank_counts["KT"][1] += tiebreak_bias
        rank_counts["KT"][2] -= tiebreak_bias
        rank_counts["SS"][1] -= tiebreak_bias
        rank_counts["SS"][2] += tiebreak_bias
    first_place_counts["KT"] = first_place_counts.get("KT", 0) + tiebreak_kt
    first_place_counts["SS"] = first_place_counts.get("SS", 0) + tiebreak_ss
    unresolved_count = int(np.count_nonzero((leader_count > 1) & ~kt_ss_tie))
    return first_place_counts, rank_counts, tiebreak_count, tiebreak_count, unresolved_count, kt_winner_mask


def compute_rank_counts(
    wins: Mapping[str, np.ndarray],
    losses: Mapping[str, np.ndarray],
) -> dict[str, dict[int, float]]:
    """Return equivalent Monte Carlo counts for each final rank.

    Exact ties that are not resolved by the configured KT-SS tiebreak receive
    fractional credit across the occupied rank interval. This keeps rank
    probabilities conservative without inventing an unmodeled tiebreak rule.
    """

    if not wins or set(wins) != set(losses):
        raise ValueError("wins and losses must contain the same non-empty teams")
    simulations = len(next(iter(wins.values())))
    if simulations == 0:
        raise ValueError("wins and losses must contain at least one simulation")
    for team in wins:
        if len(wins[team]) != simulations or len(losses[team]) != simulations:
            raise ValueError("wins and losses arrays must have the same length")
    percentages = {
        team: np.divide(
            wins[team],
            wins[team] + losses[team],
            out=np.zeros(simulations, dtype=float),
            where=(wins[team] + losses[team]) != 0,
        )
        for team in wins
    }
    return _compute_rank_counts_from_percentages(percentages, list(wins))


def _compute_rank_counts_from_percentages(
    percentages: Mapping[str, np.ndarray],
    team_ids: Sequence[str],
) -> dict[str, dict[int, float]]:
    simulations = len(next(iter(percentages.values())))
    team_count = len(team_ids)
    rank_counts = {
        team: {rank: 0.0 for rank in range(1, team_count + 1)}
        for team in team_ids
    }
    for team in team_ids:
        team_pct = percentages[team]
        strictly_better = np.zeros(simulations, dtype=np.int16)
        tied_count = np.ones(simulations, dtype=np.int16)
        for other in team_ids:
            if other == team:
                continue
            difference = percentages[other] - team_pct
            strictly_better += difference > 1e-12
            tied_count += np.abs(difference) <= 1e-12
        start_rank = strictly_better + 1
        end_rank = strictly_better + tied_count
        for rank in range(1, team_count + 1):
            occupies_rank = (start_rank <= rank) & (rank <= end_rank)
            rank_counts[team][rank] = float(np.sum(occupies_rank / tied_count))
    return rank_counts


def resolve_first_place(
    final_standings: Mapping[str, FinalStanding],
    *,
    tiebreak_probability: float,
    rng: np.random.Generator,
) -> FirstPlaceResult:
    probability = validate_probability(tiebreak_probability, "tiebreak_probability")
    best_pct = max(standing.win_pct for standing in final_standings.values())
    leaders = tuple(team for team, standing in final_standings.items() if abs(standing.win_pct - best_pct) < 1e-12)
    leader_set = set(leaders)
    if len(leaders) == 1:
        winner = leaders[0]
        return FirstPlaceResult(
            winner=winner,
            leaders=leaders,
            kt_first_place_count=int(winner == "KT"),
            ss_first_place_count=int(winner == "SS"),
            co_champion_count=0,
            tiebreak_resolved_count=0,
        )
    if leader_set == {"KT", "SS"}:
        winner = "KT" if rng.random() < probability else "SS"
        return FirstPlaceResult(
            winner=winner,
            leaders=leaders,
            kt_first_place_count=int(winner == "KT"),
            ss_first_place_count=int(winner == "SS"),
            co_champion_count=1,
            tiebreak_resolved_count=1,
        )
    return FirstPlaceResult(
        winner=None,
        leaders=leaders,
        kt_first_place_count=0,
        ss_first_place_count=0,
        co_champion_count=0,
        tiebreak_resolved_count=0,
        unresolved_count=1,
    )


def compute_magic_number(standings: list[TeamStanding], remaining: list[Game]) -> MagicNumber:
    standing_by_team = {standing.team_id: standing for standing in standings}
    kt = standing_by_team.get("KT")
    if kt is None:
        return MagicNumber(None, None, None)
    remaining_counts = {team: 0 for team in standing_by_team}
    for game in remaining:
        remaining_counts[game.away_team] = remaining_counts.get(game.away_team, 0) + 1
        remaining_counts[game.home_team] = remaining_counts.get(game.home_team, 0) + 1
    competitors = [standing for team, standing in standing_by_team.items() if team != "KT"]
    if not competitors:
        return MagicNumber(0, 0, None)
    kt_remaining = remaining_counts.get("KT", 0)
    tie_requirements: dict[str, int | None] = {}
    strict_requirements: dict[str, int | None] = {}
    max_final_pct: dict[str, float] = {}
    for competitor in competitors:
        competitor_remaining = remaining_counts.get(competitor.team_id, 0)
        head_to_head_remaining = sum(
            1
            for game in remaining
            if game.is_head_to_head("KT", competitor.team_id)
        )
        tie_needed: int | None = None
        strict_needed: int | None = None
        for wins_needed in range(kt_remaining + 1):
            kt_pct = _future_win_pct(kt, wins_needed, kt_remaining - wins_needed)
            competitor_pct = _maximum_competitor_pct(
                competitor,
                competitor_remaining,
                head_to_head_remaining,
                kt_wins=wins_needed,
                kt_remaining=kt_remaining,
            )
            if tie_needed is None and kt_pct >= competitor_pct:
                tie_needed = wins_needed
            if strict_needed is None and kt_pct > competitor_pct:
                strict_needed = wins_needed
        tie_requirements[competitor.team_id] = tie_needed
        strict_requirements[competitor.team_id] = strict_needed
        max_final_pct[competitor.team_id] = _maximum_competitor_pct(
            competitor,
            competitor_remaining,
            head_to_head_remaining,
            kt_wins=kt_remaining,
            kt_remaining=kt_remaining,
        )

    limiting_candidates = [team for team, value in strict_requirements.items() if value is None]
    if limiting_candidates:
        competitor_team = max(limiting_candidates, key=max_final_pct.__getitem__)
    else:
        competitor_team = max(strict_requirements, key=lambda team: strict_requirements[team] or 0)
    wins_needed = max(tie_requirements.values()) if all(value is not None for value in tie_requirements.values()) else None
    strict_wins_needed = (
        max(strict_requirements.values()) if all(value is not None for value in strict_requirements.values()) else None
    )
    season_games = kt.played + remaining_counts.get("KT", 0)
    competitor = standing_by_team[competitor_team]
    samsung = standing_by_team.get("SS")
    combined_tie_number = max(0, season_games - kt.wins - samsung.losses) if samsung else None
    combined_magic_number = max(0, season_games + 1 - kt.wins - samsung.losses) if samsung else None
    return MagicNumber(
        wins_needed=wins_needed,
        strict_wins_needed=strict_wins_needed,
        competitor=competitor_team,
        combined_magic_number=combined_magic_number,
        combined_tie_number=combined_tie_number,
        kt_current_wins=kt.wins,
        competitor_current_losses=competitor.losses,
        ss_current_losses=samsung.losses if samsung else None,
        season_games=season_games,
    )


def date_confirmation_probabilities(
    date_result: DateSimulationResult | SimulationResult,
) -> list[DateConfirmation]:
    dates = date_result.first_confirmation_dates
    counts = Counter(value for value in dates if value is not None)
    denominator = len(dates)
    return [DateConfirmation(day, count / denominator, count) for day, count in sorted(counts.items())]


def _future_win_pct(standing: TeamStanding, additional_wins: int, additional_losses: int) -> float:
    wins = standing.wins + additional_wins
    losses = standing.losses + additional_losses
    return wins / (wins + losses) if wins + losses else 0.0


def _maximum_competitor_pct(
    competitor: TeamStanding,
    competitor_remaining: int,
    head_to_head_remaining: int,
    *,
    kt_wins: int,
    kt_remaining: int,
) -> float:
    forced_kt_head_to_head_wins = max(0, kt_wins - max(0, kt_remaining - head_to_head_remaining))
    forced_kt_head_to_head_wins = min(forced_kt_head_to_head_wins, head_to_head_remaining)
    competitor_additional_wins = competitor_remaining - forced_kt_head_to_head_wins
    return _future_win_pct(competitor, competitor_additional_wins, forced_kt_head_to_head_wins)


def _remaining_counts_after_date(games: Sequence[Game], game_date: date) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for game in games:
        if game.simulation_date is None or game.simulation_date > game_date:
            counts[game.away_team] += 1
            counts[game.home_team] += 1
    return counts


def _kt_is_safe(
    wins: dict[str, np.ndarray],
    losses: dict[str, np.ndarray],
    remaining: Mapping[str, int],
    simulations: int,
) -> np.ndarray:
    kt_decisions = wins["KT"] + losses["KT"] + remaining.get("KT", 0)
    kt_min_pct = np.divide(wins["KT"], kt_decisions, out=np.zeros(simulations, dtype=float), where=kt_decisions != 0)
    safe = np.ones(simulations, dtype=bool)
    for team in wins:
        if team == "KT":
            continue
        competitor_decisions = wins[team] + losses[team]
        competitor_max_pct = np.divide(
            wins[team] + remaining.get(team, 0),
            competitor_decisions + remaining.get(team, 0),
            out=np.zeros(simulations, dtype=float),
            where=(competitor_decisions + remaining.get(team, 0)) != 0,
        )
        safe &= kt_min_pct > competitor_max_pct
    return safe


def _head_to_head_tiebreak_probability(forecasts: list[GameForecast], snapshot: Snapshot) -> float:
    for forecast in reversed(forecasts):
        if not forecast.is_remaining:
            continue
        game = next((candidate for candidate in snapshot.games if candidate.game_id == forecast.game_id), None)
        if game is not None and game.is_head_to_head("KT", "SS"):
            probability = forecast.combined_probability
            if probability is None:
                probability = forecast.base_probability
            if probability is None:
                raise ValueError(f"missing tie-break probability for {game.game_id}")
            return probability if forecast.team == "KT" else 1.0 - probability
    return 0.5
