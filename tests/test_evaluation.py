import pytest

from kt_championship_engine.evaluation import brier_scores


def test_brier_scores_are_separated_by_model(scored_forecasts):
    scores = brier_scores(scored_forecasts)
    assert scores["base"] == pytest.approx(0.25)
    assert scores["jev"] == pytest.approx(0.25)
    assert scores["combined"] == pytest.approx(0.25)


def test_brier_score_rejects_no_actual_results(forecasts):
    with pytest.raises(ValueError, match="no scored predictions"):
        brier_scores(forecasts)
