from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from kt_championship_engine.config import EngineConfig
from kt_championship_engine.data_io import load_snapshot
from kt_championship_engine.features import GameFeatures
from kt_championship_engine.schemas import Game, GameForecast, Snapshot

AS_OF = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


@pytest.fixture
def mini_snapshot() -> Snapshot:
    return load_snapshot(Path(__file__).parents[1] / "data/fixtures/mini_snapshot.json")


@pytest.fixture
def stale_snapshot(mini_snapshot: Snapshot) -> Snapshot:
    return mini_snapshot.model_copy(
        deep=True,
        update={"manifest": mini_snapshot.manifest.model_copy(update={"as_of": datetime(2026, 9, 19, 12, 0, tzinfo=UTC)})},
    )


@pytest.fixture
def game_factory():
    def make_game(**overrides):
        values = {
            "game_id": "20260920-KT-SS-01",
            "season": 2026,
            "game_date": date(2026, 9, 20),
            "status": "scheduled",
            "away_team": "KT",
            "home_team": "SS",
            "away_score": None,
            "home_score": None,
            "is_official_result": False,
            "source_type": "official",
            "as_of": AS_OF,
            "retrieved_at": AS_OF,
            "source_uri": "https://example.test/game",
            "source_hash": "a" * 64,
        }
        values.update(overrides)
        return Game.model_validate(values)

    return make_game


@pytest.fixture
def game(game_factory):
    return game_factory(game_id="model-game", away_team="SS", home_team="KT")


@pytest.fixture
def model_features(mini_snapshot):
    from kt_championship_engine.features import build_team_features

    return build_team_features(mini_snapshot)


@pytest.fixture
def game_features(game, model_features):
    return GameFeatures.from_game(game, model_features)


@pytest.fixture
def config():
    return EngineConfig(
        as_of=AS_OF,
        simulations=100,
        base_weight=0.60,
        jev_weight=0.40,
    )


@pytest.fixture
def forecasts(mini_snapshot):
    return [
        GameForecast(
            game_id=game.game_id,
            team=game.home_team,
            opponent=game.away_team,
            is_home=True,
            base_probability=0.60,
            combined_probability=0.60,
            jev_status="unavailable",
        )
        for game in mini_snapshot.games
        if game.remaining
    ]


@pytest.fixture
def equal_final_standings():
    from kt_championship_engine.simulation import FinalStanding

    return {
        "KT": FinalStanding(team="KT", wins=80, losses=64, ties=0),
        "SS": FinalStanding(team="SS", wins=80, losses=64, ties=0),
    }


@pytest.fixture
def date_result():
    from datetime import date

    from kt_championship_engine.simulation import DateSimulationResult

    return DateSimulationResult(first_confirmation_dates=[date(2026, 9, 21), date(2026, 9, 21), date(2026, 9, 22), None])


@pytest.fixture
def scored_forecasts():
    return [
        GameForecast(
            game_id="scored-1",
            team="KT",
            opponent="SS",
            base_probability=0.5,
            jev_probability=0.5,
            combined_probability=0.5,
            jev_status="ok",
            actual_result="win",
        )
    ]


@pytest.fixture
def simulation_result(mini_snapshot, forecasts):
    from kt_championship_engine.simulation import simulate

    return simulate(mini_snapshot, forecasts, simulations=100, seed=7)


@pytest.fixture
def manifest(mini_snapshot):
    return mini_snapshot.manifest


@pytest.fixture
def fixture_snapshot():
    return Path(__file__).parents[1] / "data/fixtures/mini_snapshot.json"


@pytest.fixture
def cli_runner():
    from typer.testing import CliRunner

    return CliRunner()
