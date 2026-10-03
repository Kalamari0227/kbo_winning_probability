from __future__ import annotations

import csv
import json
from datetime import UTC, date, datetime
from pathlib import Path

import typer

from .collectors import CollectorError, KBOCollector
from .config import EngineConfig, merge_config
from .data_io import load_snapshot, save_snapshot
from .evaluation import brier_scores
from .features import build_team_features
from .forecasting import build_forecasts
from .reporting import write_run_artifacts
from .scheduling import ESTIMATED_MAKEUP_DATE_METHOD, estimate_makeup_dates
from .schemas import GameForecast
from .simulation import (
    compute_magic_number,
    date_confirmation_probabilities,
    simulate,
)
from .validation import SnapshotValidationError, validate_snapshot

app = typer.Typer(no_args_is_help=True, add_completion=False)
TEAM_LABELS = {"SS": "삼성"}


@app.command()
def collect(
    as_of: str | None = typer.Option(None, help="optional analysis date, YYYY-MM-DD; defaults to latest official cutoff"),
    output: Path = typer.Option(Path("data/snapshots/latest.json"), help="snapshot output path"),
) -> None:
    """Fetch and preserve an official KBO snapshot."""

    try:
        snapshot = KBOCollector().fetch(date.fromisoformat(as_of) if as_of else None)
        save_snapshot(snapshot, output)
    except (CollectorError, ValueError) as exc:
        typer.echo(f"collect failed: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(f"saved official snapshot: {output}")


@app.command()
def validate(
    snapshot: Path = typer.Option(..., exists=True, readable=True),
    as_of: str | None = typer.Option(None, help="optional cutoff ISO datetime; defaults to snapshot cutoff"),
    allow_stale: bool = typer.Option(False, help="allow an older official snapshot"),
) -> None:
    """Validate a normalized snapshot and its provenance."""

    try:
        loaded = load_snapshot(snapshot)
        report = validate_snapshot(
            loaded,
            as_of=_parse_datetime(as_of) if as_of else loaded.manifest.as_of,
            allow_stale=allow_stale,
        )
    except (SnapshotValidationError, ValueError) as exc:
        typer.echo(f"validation failed: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))


@app.command()
def run(
    snapshot: Path = typer.Option(..., exists=True, readable=True),
    simulations: int | None = typer.Option(None, min=1),
    seed: int | None = typer.Option(None),
    output: Path = typer.Option(Path("artifacts/latest")),
    config: Path = typer.Option(Path("config/default.toml"), "--config"),
    as_of: str | None = typer.Option(None, help="cutoff ISO datetime"),
    allow_stale: bool | None = typer.Option(None, "--allow-stale/--no-allow-stale"),
    no_jev: bool = typer.Option(False, help="disable Jev and record disabled status"),
) -> None:
    """Run Base/Jev forecasts and deterministic Monte Carlo simulation."""

    try:
        loaded = load_snapshot(snapshot)
        estimated_games = estimate_makeup_dates(loaded.games)
        estimated_makeup_count = sum(game.estimated_game_date is not None for game in estimated_games)
        if estimated_makeup_count and loaded.manifest.estimated_schedule_method is None:
            loaded = loaded.model_copy(
                update={
                    "games": estimated_games,
                    "manifest": loaded.manifest.model_copy(
                        update={
                            "warnings": [
                                *loaded.manifest.warnings,
                                f"estimated {estimated_makeup_count} undated postponed games for simulation",
                            ],
                            "estimated_schedule_method": ESTIMATED_MAKEUP_DATE_METHOD,
                        }
                    ),
                }
            )
        elif estimated_games != loaded.games:
            loaded = loaded.model_copy(update={"games": estimated_games})
        engine_config = _load_config(
            config,
            as_of,
            simulations,
            seed,
            allow_stale,
            default_as_of=loaded.manifest.as_of,
        )
        validation = validate_snapshot(
            loaded,
            as_of=engine_config.as_of,
            allow_stale=engine_config.allow_stale,
        )
        run_manifest = loaded.manifest.model_copy(
            update={
                "stale": validation.stale,
                "warnings": list(dict.fromkeys([*loaded.manifest.warnings, *validation.warnings])),
                "official_record_count": validation.official_count,
                "estimated_record_count": validation.estimated_count,
                "inferred_schedule_record_count": validation.inferred_schedule_count,
            }
        )
        features = build_team_features(loaded)
        forecasts = build_forecasts(loaded, features, engine_config, no_jev=no_jev)
        result = simulate(loaded, forecasts, simulations=engine_config.simulations, seed=engine_config.seed)
        magic_number = compute_magic_number(loaded.standings, [game for game in loaded.games if game.remaining])
        artifacts = write_run_artifacts(result, forecasts, run_manifest, output, engine_config, magic_number)
    except (SnapshotValidationError, ValueError) as exc:
        typer.echo(f"run failed: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    typer.echo("KT Championship Engine")
    summary = json.loads(artifacts.summary_json.read_text(encoding="utf-8"))
    mode_label = {"base_only": "Base-only", "mixed_base_jev": "Base + Jev", "jev_adjusted": "Base + Jev"}
    typer.echo(f"결과 모드: {mode_label[summary['forecast_mode']]}")
    typer.echo(f"KT 1위 확률: {result.rank_probability('KT', 1):.4%}")
    typer.echo(f"삼성 1위 확률: {result.rank_probability('SS', 1):.4%}")
    typer.echo(f"LG 1위 확률: {result.rank_probability('LG', 1):.4%}")
    typer.echo("최종 1~3위 확률")
    rank_order = sorted(
        result.rank_counts,
        key=lambda team: (-result.top_three_probability(team), -result.rank_probability(team, 1), team),
    )
    for team in rank_order:
        label = TEAM_LABELS.get(team, team)
        typer.echo(
            f"{label}: 1위 {result.rank_probability(team, 1):.2%}, "
            f"2위 {result.rank_probability(team, 2):.2%}, "
            f"3위 {result.rank_probability(team, 3):.2%}, "
            f"Top3 {result.top_three_probability(team):.2%}"
        )
    typer.echo(f"KT 예상 최종승수: {result.team_win_totals['KT'].mean():.2f}")
    typer.echo(f"삼성 예상 최종승수: {result.team_win_totals['SS'].mean():.2f}")
    typer.echo(f"LG 예상 최종승수: {result.team_win_totals['LG'].mean():.2f}")
    if magic_number.combined_magic_number is not None:
        typer.echo(f"KT-삼성 결합 매직넘버: {magic_number.combined_magic_number}")
        typer.echo(f"현재 매직넘버(결합): {magic_number.combined_magic_number}")
        typer.echo("계산: 승/(승+패) 정확 비교, 현재 무승부 및 잔여 맞대결 연동; 맞대결 KT 승은 2개")
        typer.echo("결합은 삼성 상대 보장, 자력 추가승은 전체 경쟁팀 상대 보장; 동률은 우승 미확정")
        typer.echo(f"KT 단독 매직넘버(추가 승리): {magic_number.strict_wins_needed}")
        typer.echo(f"KT 단독 추가승수(동률 또는 타이브레이크 기준): {magic_number.wins_needed}")
        typer.echo(f"삼성 이상 승률 보장 기준(결합): {magic_number.combined_tie_number}")
    else:
        typer.echo(f"현재 매직넘버: {magic_number.wins_needed}")
    date_rows = date_confirmation_probabilities(result)
    if date_rows:
        most_likely = max(date_rows, key=lambda row: row.probability)
        typer.echo(f"가장 유력한 KT 1위 확정일: {most_likely.date.isoformat()} ({most_likely.probability:.2%})")
        typer.echo("날짜별 확정 확률:")
        for row in date_rows:
            typer.echo(f"  {row.date.isoformat()}: {row.probability:.2%}")
        typer.echo(
            f"순연경기 날짜 추정: {summary['estimated_makeup_date_count']}경기 "
            f"({summary['estimated_makeup_date_start']}~{summary['estimated_makeup_date_end']})"
            if summary["estimated_makeup_date_count"]
            else "순연경기 날짜 추정: 없음"
        )
    else:
        typer.echo("가장 유력한 KT 1위 확정일: unknown")
    typer.echo(f"Jev API 사전 점검: {summary['jev_preflight_display']}")
    typer.echo(f"Jev 호출 성공 경기 수: {summary['jev_successful_game_count']}")
    typer.echo(f"Jev 호출 실패 경기 수: {summary['jev_failed_call_count']}")
    typer.echo(f"Base-only 경기 수: {summary['base_only_game_count']}")
    typer.echo(f"데이터 기준시각: {summary['data_as_of']}")
    typer.echo(f"데이터 수집시각: {summary['data_retrieved_at']}")
    typer.echo(f"linked head-to-head samples: {result.linked_game_sample_count}")
    typer.echo(f"산출물: {artifacts.summary_md}")


@app.command()
def evaluate(
    predictions: Path = typer.Option(..., exists=True, readable=True),
    results: Path | None = typer.Option(None, exists=True, readable=True),
) -> None:
    """Join actual results and print Base/Jev/Combined Brier Scores."""

    actuals: dict[tuple[str, str], tuple[str, str | None]] = {}
    if results is not None:
        with results.open("r", newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                actuals[(row["game_id"], row["team"])] = (
                    row["actual_result"],
                    row.get("result_source"),
                )
    rows: list[GameForecast] = []
    with predictions.open("r", newline="", encoding="utf-8") as stream:
        for raw in csv.DictReader(stream):
            normalized = _normalize_forecast_csv_row(raw)
            forecast = GameForecast.model_validate(normalized)
            actual_result, result_source = actuals.get((forecast.game_id, forecast.team), (None, None))
            if actual_result:
                values = forecast.model_dump(mode="python")
                values.update({"actual_result": actual_result, "result_source": result_source})
                forecast = GameForecast.model_validate(values)
            rows.append(forecast)
    try:
        scores = brier_scores(rows)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(json.dumps(scores, ensure_ascii=False, indent=2, allow_nan=True))


@app.command(help="로컬 대시보드를 열고 필요 시 KBO 자료를 갱신합니다.")
def serve(
    host: str = typer.Option("127.0.0.1", help="dashboard bind address"),
    port: int = typer.Option(8765, min=1, max=65535, help="dashboard port"),
) -> None:
    from .web_server import serve_dashboard

    try:
        serve_dashboard(Path.cwd(), host=host, port=port)
    except RuntimeError as exc:
        typer.echo(f"dashboard failed: {exc}", err=True)
        raise typer.Exit(code=2) from exc


@app.command("build-pages", help="GitHub Pages에 올릴 정적 대시보드 파일을 생성합니다.")
def build_pages_command(
    output: Path = typer.Option(Path("_site"), help="static site output directory"),
) -> None:
    from .pages import build_pages

    try:
        source = build_pages(Path.cwd(), output)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        typer.echo(f"static page build failed: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(f"static dashboard built at {output} from {source}")


def _normalize_forecast_csv_row(raw: dict[str, str]) -> dict[str, object]:
    normalized: dict[str, object] = dict(raw)
    nullable_fields = {
        "base_probability",
        "jev_probability",
        "combined_probability",
        "jev_confidence",
        "jev_http_status",
        "jev_message",
        "jev_request_hash",
        "jev_model",
        "jev_reason_code",
        "effective_base_weight",
        "effective_jev_weight",
        "actual_result",
        "result_source",
        "predicted_at",
        "game_date",
        "estimated_game_date",
    }
    for key in nullable_fields:
        if normalized.get(key) == "":
            normalized[key] = None
    components = normalized.get("jev_components")
    if components in (None, ""):
        normalized["jev_components"] = {}
    elif isinstance(components, str):
        try:
            parsed = json.loads(components)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid jev_components JSON in forecast CSV: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("jev_components in forecast CSV must be an object")
        normalized["jev_components"] = parsed
    return normalized


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _load_config(
    path: Path,
    as_of: str | None,
    simulations: int | None,
    seed: int | None,
    allow_stale: bool | None,
    *,
    default_as_of: datetime,
) -> EngineConfig:
    loaded = (
        EngineConfig.from_toml(path, default_as_of=default_as_of)
        if path.exists()
        else EngineConfig(as_of=_parse_datetime(as_of) if as_of else default_as_of)
    )
    return merge_config(
        loaded,
        as_of=_parse_datetime(as_of) if as_of else None,
        simulations=simulations,
        seed=seed,
        allow_stale=allow_stale,
    )


if __name__ == "__main__":
    app()
