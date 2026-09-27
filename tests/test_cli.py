import pytest

from kt_championship_engine.cli import app


def test_run_command_writes_summary(cli_runner, fixture_snapshot, tmp_path):
    result = cli_runner.invoke(
        app,
        [
            "run",
            "--snapshot",
            str(fixture_snapshot),
            "--simulations",
            "100",
            "--seed",
            "2",
            "--output",
            str(tmp_path),
            "--no-jev",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert (tmp_path / "summary.md").exists()
    assert "현재 매직넘버(결합)" in result.stdout
    assert "동률 도달 기준(결합)" in result.stdout
    assert "KT 단독 추가승수" in result.stdout


def test_run_command_prints_top_three_rank_forecast(cli_runner, fixture_snapshot, tmp_path):
    result = cli_runner.invoke(
        app,
        [
            "run",
            "--snapshot",
            str(fixture_snapshot),
            "--simulations",
            "100",
            "--seed",
            "2",
            "--output",
            str(tmp_path),
            "--no-jev",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert "최종 1~3위 확률" in result.stdout
    assert "LG" in result.stdout


def test_run_records_actual_results_and_labels_zero_jev_as_base_only(
    cli_runner, fixture_snapshot, tmp_path, monkeypatch
):
    import csv
    import json

    from kt_championship_engine.models.jev import JevJudgment
    from kt_championship_engine.schemas import JevStatus

    class MissingKeyJevClient:
        def __init__(self, config):
            pass

        def smoke_test(self, game, features):
            return JevJudgment(
                status=JevStatus.UNAVAILABLE,
                message="TYPESAFE_API_KEY missing",
                call_attempted=False,
                reason_code="missing_api_key",
            )

        def judge(self, game, features):
            raise AssertionError("Jev calls must stop when the smoke test has no key")

        def close(self):
            pass

    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setattr("kt_championship_engine.forecasting.HttpJevClient", MissingKeyJevClient)
    output = tmp_path / "run"
    result = cli_runner.invoke(
        app,
        [
            "run",
            "--snapshot",
            str(fixture_snapshot),
            "--as-of",
            "2026-09-20T12:00:00+00:00",
            "--simulations",
            "20",
            "--seed",
            "7",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "결과 모드: Base-only" in result.stdout
    assert "Jev API 사전 점검: 미수행 (TYPESAFE_API_KEY 없음)" in result.stdout
    assert "Jev 호출 성공 경기 수: 0" in result.stdout
    assert "Jev 호출 실패 경기 수: 0" in result.stdout
    assert "Base-only 경기 수: 3" in result.stdout
    summary = json.loads((output / "simulation_summary.json").read_text(encoding="utf-8"))
    assert summary["forecast_mode"] == "base_only"
    assert summary["jev_successful_game_count"] == 0
    assert summary["jev_failed_call_count"] == 0
    assert summary["base_only_game_count"] == 3
    assert "LG" in summary["final_win_stats"]
    for rank in ("1", "2", "3"):
        assert sum(row[rank] for row in summary["rank_probabilities"].values()) == pytest.approx(1.0)
    with (output / "game_forecasts.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    actual = next(row for row in rows if row["game_id"] == "20260919-KT-DO-01")
    assert actual["actual_result"] == "win"
    assert actual["jev_status"] == "not_applicable"


def test_validate_rejects_stale_without_flag(cli_runner, stale_snapshot, tmp_path):
    from kt_championship_engine.data_io import save_snapshot

    snapshot_path = tmp_path / "stale.json"
    save_snapshot(stale_snapshot, snapshot_path)
    result = cli_runner.invoke(app, ["validate", "--snapshot", str(snapshot_path)])
    assert result.exit_code != 0


def test_run_records_configured_weights(cli_runner, fixture_snapshot, tmp_path):
    config_path = tmp_path / "engine.toml"
    config_path.write_text(
        'as_of = "2026-09-20T12:00:00+00:00"\nbase_weight = 0.25\njev_weight = 0.75\nsimulations = 10\nseed = 7\n',
        encoding="utf-8",
    )
    output = tmp_path / "run"
    result = cli_runner.invoke(
        app,
        [
            "run",
            "--snapshot",
            str(fixture_snapshot),
            "--config",
            str(config_path),
            "--output",
            str(output),
            "--no-jev",
        ],
    )
    assert result.exit_code == 0, result.stdout
    import json

    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert summary["configured_base_weight"] == 0.25
    assert summary["simulations"] == 10


def test_evaluate_reads_own_nullable_forecast_csv(cli_runner, fixture_snapshot, tmp_path):
    import csv

    run_output = tmp_path / "run"
    run_result = cli_runner.invoke(
        app,
        [
            "run",
            "--snapshot",
            str(fixture_snapshot),
            "--simulations",
            "10",
            "--seed",
            "7",
            "--output",
            str(run_output),
            "--no-jev",
        ],
    )
    assert run_result.exit_code == 0, run_result.stdout
    with (run_output / "game_forecasts.csv").open(encoding="utf-8", newline="") as stream:
        first_game = next(row for row in csv.DictReader(stream) if row["is_remaining"] == "True")
    results_path = tmp_path / "results.csv"
    results_path.write_text(
        "game_id,team,actual_result,result_source,result_recorded_at\n"
        f"{first_game['game_id']},{first_game['team']},win,official,2026-09-21T00:00:00Z\n",
        encoding="utf-8",
    )
    evaluate_result = cli_runner.invoke(
        app,
        [
            "evaluate",
            "--predictions",
            str(run_output / "game_forecasts.csv"),
            "--results",
            str(results_path),
        ],
    )
    assert evaluate_result.exit_code == 0, evaluate_result.stdout


def test_run_records_allowed_stale_snapshot(cli_runner, stale_snapshot, tmp_path):
    from kt_championship_engine.data_io import save_snapshot

    snapshot_path = tmp_path / "stale.json"
    save_snapshot(stale_snapshot, snapshot_path)
    output = tmp_path / "run"
    result = cli_runner.invoke(
        app,
        [
            "run",
            "--snapshot",
            str(snapshot_path),
            "--simulations",
            "10",
            "--seed",
            "7",
            "--as-of",
            "2026-09-20T12:00:00+00:00",
            "--output",
            str(output),
            "--allow-stale",
            "--no-jev",
        ],
    )
    assert result.exit_code == 0, result.stdout
    import json

    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert summary["data_stale"] is True
    assert summary["warnings"]
