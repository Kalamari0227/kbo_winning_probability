import pytest

from kt_championship_engine.evaluation import brier_scores
from kt_championship_engine.reporting import write_run_artifacts
from kt_championship_engine.schemas import GameForecast, JevStatus, SourceType
from kt_championship_engine.simulation import compute_magic_number


def test_report_contains_provenance_and_top_risk(tmp_path, simulation_result, forecasts, manifest, mini_snapshot):
    magic_number = compute_magic_number(
        mini_snapshot.standings,
        [game for game in mini_snapshot.games if game.remaining],
    )
    artifacts = write_run_artifacts(simulation_result, forecasts, manifest, tmp_path, magic_number=magic_number)
    text = artifacts.summary_md.read_text(encoding="utf-8")
    assert "데이터 갱신 시각" in text
    assert "위험 경기 TOP 5" in text
    assert "최종 1~3위 확률" in text
    assert "현재 매직넘버(결합)" in text
    assert "삼성 이상 승률 보장 기준(결합)" in text
    assert "KT 단독 추가승수" in text
    assert artifacts.game_forecasts_csv.exists()
    assert artifacts.final_wins_distribution_csv.exists()
    assert artifacts.final_rank_distribution_csv.exists()


def test_report_preserves_forecast_probabilities_when_game_becomes_final(
    tmp_path, simulation_result, manifest
):
    predicted = GameForecast(
        game_id="forecast-history-1",
        team="KT",
        opponent="SS",
        is_home=True,
        base_probability=0.6,
        jev_probability=0.7,
        combined_probability=0.64,
        jev_status=JevStatus.OK,
        jev_call_attempted=True,
    )
    output = tmp_path / "history"
    write_run_artifacts(simulation_result, [predicted], manifest, output)
    final = GameForecast(
        game_id=predicted.game_id,
        team=predicted.team,
        opponent=predicted.opponent,
        is_home=True,
        is_remaining=False,
        jev_status=JevStatus.NOT_APPLICABLE,
        actual_result="win",
        result_source=SourceType.OFFICIAL,
    )

    artifacts = write_run_artifacts(simulation_result, [final], manifest, output)

    import csv

    with artifacts.game_forecasts_csv.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 1
    assert rows[0]["actual_result"] == "win"
    assert rows[0]["is_remaining"] == "False"
    assert float(rows[0]["base_probability"]) == pytest.approx(0.6)
    assert float(rows[0]["jev_probability"]) == pytest.approx(0.7)
    assert brier_scores([GameForecast.model_validate(_normalized_row(rows[0]))])["combined"] == pytest.approx(0.1296)


def test_report_drops_stale_remaining_forecast_when_game_disappears(tmp_path, simulation_result, manifest):
    stale = GameForecast(
        game_id="old-schedule-id",
        team="KT",
        opponent="SS",
        is_home=True,
        base_probability=0.6,
        combined_probability=0.6,
    )
    current = GameForecast(
        game_id="current-schedule-id",
        team="KT",
        opponent="SS",
        is_home=True,
        base_probability=0.55,
        combined_probability=0.55,
    )
    output = tmp_path / "history"
    write_run_artifacts(simulation_result, [stale], manifest, output)

    artifacts = write_run_artifacts(simulation_result, [current], manifest, output)

    import csv

    with artifacts.game_forecasts_csv.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert [row["game_id"] for row in rows] == ["current-schedule-id"]


def _normalized_row(row):
    normalized = dict(row)
    normalized["jev_call_attempted"] = normalized["jev_call_attempted"] == "True"
    normalized["jev_is_preflight"] = normalized["jev_is_preflight"] == "True"
    normalized["is_remaining"] = normalized["is_remaining"] == "True"
    normalized["jev_components"] = {}
    nullable_fields = (
        "game_date",
        "estimated_game_date",
        "jev_http_status",
        "jev_reason_code",
        "jev_confidence",
        "jev_message",
        "jev_request_hash",
        "jev_model",
        "effective_base_weight",
        "effective_jev_weight",
        "predicted_at",
    )
    for key in nullable_fields:
        normalized[key] = normalized[key] or None
    return normalized
