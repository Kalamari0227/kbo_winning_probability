import subprocess
import sys
from datetime import date
from pathlib import Path

import numpy as np

from kt_championship_engine import simulation as simulation_module
from kt_championship_engine.scheduling import estimate_makeup_dates
from kt_championship_engine.simulation import (
    compute_magic_number,
    date_confirmation_probabilities,
    resolve_first_place,
    simulate,
)


def test_head_to_head_is_sampled_once(mini_snapshot, forecasts):
    result = simulate(mini_snapshot, forecasts, simulations=2000, seed=7)
    assert result.linked_game_sample_count == 1
    assert result.team_win_totals["KT"].max() - result.team_win_totals["SS"].max() <= 2


def test_confirmation_date_simulates_estimated_postponement_date(mini_snapshot, forecasts):
    snapshot = mini_snapshot.model_copy(update={"games": estimate_makeup_dates(mini_snapshot.games)})

    result = simulate(snapshot, forecasts, simulations=20_000, seed=7)

    assert date(2026, 9, 23) in result.first_confirmation_dates


def test_tiebreak_resolves_co_champion(equal_final_standings):
    result = resolve_first_place(
        equal_final_standings,
        tiebreak_probability=0.70,
        rng=np.random.default_rng(3),
    )
    assert result.co_champion_count >= result.kt_first_place_count
    assert result.kt_first_place_count + result.ss_first_place_count == result.tiebreak_resolved_count


def test_three_way_tie_is_not_resolved_by_kt_ss_tiebreak():
    final_standing = __import__("kt_championship_engine.simulation", fromlist=["FinalStanding"]).FinalStanding
    standings = {team: final_standing(team, 80, 64, 0) for team in ("KT", "SS", "LG")}
    result = resolve_first_place(standings, tiebreak_probability=0.70, rng=np.random.default_rng(3))
    assert result.winner is None
    assert result.co_champion_count == 0
    assert result.unresolved_count == 1


def test_compute_rank_counts_assigns_fractional_credit_for_unresolved_ties():
    wins = {
        "KT": np.array([90, 80]),
        "SS": np.array([89, 80]),
        "LG": np.array([88, 79]),
        "NC": np.array([87, 79]),
    }
    losses = {
        "KT": np.array([54, 64]),
        "SS": np.array([55, 64]),
        "LG": np.array([56, 65]),
        "NC": np.array([57, 65]),
    }

    compute_rank_counts = getattr(simulation_module, "compute_rank_counts", None)
    assert compute_rank_counts is not None
    counts = compute_rank_counts(wins, losses)

    assert counts["KT"][1] == 1.5
    assert counts["KT"][2] == 0.5
    assert counts["SS"][1] == 0.5
    assert counts["SS"][2] == 1.5
    assert counts["LG"][3] == 1.5
    assert counts["NC"][3] == 0.5


def test_magic_number_checks_every_contender(game_factory):
    from kt_championship_engine.schemas import TeamStanding

    standings = [
        TeamStanding(
            season=2026,
            team_id=team,
            team_name=team,
            played=wins + losses,
            wins=wins,
            losses=losses,
            ties=0,
            win_pct=wins / (wins + losses),
            rank=rank,
            as_of=game_factory().as_of,
            retrieved_at=game_factory().retrieved_at,
            source_type="official",
        )
        for team, wins, losses, rank in (("KT", 50, 30, 1), ("SS", 48, 32, 2), ("LG", 47, 33, 3))
    ]
    remaining = [
        game_factory(game_id=f"kt-ss-{index}", away_team="KT", home_team="SS") for index in range(1)
    ] + [
        game_factory(game_id=f"kt-lg-{index}", away_team="KT", home_team="LG") for index in range(1)
    ] + [
        game_factory(game_id=f"lg-x-{index}", away_team="LG", home_team="NC") for index in range(19)
    ]
    result = compute_magic_number(standings, remaining)
    assert result.wins_needed is None
    assert result.competitor == "LG"


def test_magic_number_reports_combined_leader_wins_and_competitor_losses(game_factory):
    from kt_championship_engine.schemas import TeamStanding

    standings = [
        TeamStanding(
            season=2026,
            team_id=team,
            team_name=team,
            played=played,
            wins=wins,
            losses=losses,
            ties=ties,
            win_pct=wins / (wins + losses),
            rank=rank,
            as_of=game_factory().as_of,
            retrieved_at=game_factory().retrieved_at,
            source_type="official",
        )
        for team, played, wins, losses, ties, rank in (
            ("KT", 129, 78, 47, 4, 1),
            ("SS", 131, 76, 52, 3, 2),
            ("LG", 131, 75, 55, 1, 3),
        )
    ]
    remaining = [
        game_factory(game_id=f"kt-{index}", away_team="KT", home_team="LG") for index in range(15)
    ] + [
        game_factory(game_id=f"ss-{index}", away_team="SS", home_team="LG") for index in range(13)
    ]

    result = compute_magic_number(standings, remaining)

    assert getattr(result, "combined_magic_number", None) == 15
    assert getattr(result, "combined_tie_number", None) == 14
    assert getattr(result, "kt_current_wins", None) == 78
    assert getattr(result, "competitor_current_losses", None) == 52


def test_date_confirmation_probabilities_sum_to_at_most_one(date_result):
    probabilities = date_confirmation_probabilities(date_result)
    assert sum(row.probability for row in probabilities) <= 1.0 + 1e-12
    assert probabilities[0].date == date(2026, 9, 21)


def test_module_run_smoke_command(tmp_path):
    snapshot = Path(__file__).parents[1] / "data/fixtures/mini_snapshot.json"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "kt_championship_engine",
            "run",
            "--snapshot",
            str(snapshot),
            "--simulations",
            "10000",
            "--seed",
            "7",
            "--output",
            str(tmp_path),
            "--no-jev",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "KT 1위 확률" in completed.stdout
    assert "linked head-to-head samples: 1" in completed.stdout


def test_simulation_resolves_first_place_in_batch(mini_snapshot, forecasts, monkeypatch):
    def scalar_resolution_should_not_run(*args, **kwargs):
        raise AssertionError("scalar first-place resolution was called")

    monkeypatch.setattr(simulation_module, "resolve_first_place", scalar_resolution_should_not_run)
    result = simulate(mini_snapshot, forecasts, simulations=32, seed=7)
    assert result.first_place_counts["KT"] + result.first_place_counts["SS"] <= 32
