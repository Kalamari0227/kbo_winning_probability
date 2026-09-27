from datetime import UTC, datetime

import pytest

from kt_championship_engine.schemas import GameForecast, Provenance, TeamStanding


def test_game_with_undated_postponement_is_remaining(game_factory):
    game = game_factory(status="postponed", game_date=None)
    assert game.remaining is True


def test_final_game_with_missing_score_is_invalid(game_factory):
    with pytest.raises(ValueError, match="final game requires both scores"):
        game_factory(status="final", is_official_result=True)


def test_non_final_game_with_score_is_invalid(game_factory):
    with pytest.raises(ValueError, match="non-final game cannot carry a score"):
        game_factory(status="scheduled", away_score=1, home_score=0)


def test_probability_rejects_out_of_range():
    with pytest.raises(ValueError):
        GameForecast(
            game_id="g",
            team="KT",
            opponent="SSG",
            base_probability=1.2,
        )


def test_head_to_head_is_order_independent(game_factory):
    game = game_factory()
    assert game.is_head_to_head("SS", "KT") is True
    assert game.is_head_to_head("KT", "LG") is False


def test_standing_rejects_inconsistent_played_count():
    with pytest.raises(ValueError, match="played must equal wins \\+ losses \\+ ties"):
        TeamStanding(
            season=2026,
            team_id="KT",
            team_name="KT Wiz",
            played=10,
            wins=6,
            losses=3,
            ties=0,
            win_pct=0.667,
            rank=1,
            as_of=datetime(2026, 9, 20, tzinfo=UTC),
            retrieved_at=datetime(2026, 9, 20, tzinfo=UTC),
            source_type="official",
            source_uri="https://example.test/standings",
            source_hash="b" * 64,
        )


def test_provenance_rejects_as_of_after_retrieval():
    with pytest.raises(ValueError, match="as_of cannot be after retrieved_at"):
        Provenance(
            as_of=datetime(2026, 9, 20, 15, tzinfo=UTC),
            retrieved_at=datetime(2026, 9, 20, 14, tzinfo=UTC),
            source_type="official",
        )
