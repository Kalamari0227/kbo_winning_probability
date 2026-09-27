# KT Championship Engine v0.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 공식·추정 데이터의 provenance를 보존하면서 KT와 삼성의 2026 KBO 정규시즌 단독 1위 확률을 계산하는 실행 가능한 Python CLI를 만든다.

**Architecture:** 입력 스냅샷과 수집기를 정규화된 dataclass 계약으로 통합하고, 검증된 잔여경기를 Base 모델과 Jev 어댑터에 전달한다. 경기 확률은 설정 가능한 60/40 결합으로 만든 뒤 결정론적 NumPy 시뮬레이터가 전체 리그 순위, KT–삼성 단일 맞대결, 동률 결정전, 날짜별 확정 상태를 계산한다. 실행 결과는 CSV·JSON·Markdown 감사 산출물로 남기며 결과가 누적되면 동일한 예측 레코드로 Brier Score를 평가한다.

**Tech Stack:** Python 3.11+, NumPy, Pydantic v2, httpx, pandas, Typer, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-09-20-kt-championship-engine-design.md`

## Global Constraints

- KBO 정규시즌은 팀당 정확히 144경기로 계산한다.
- 날짜가 확정되지 않은 취소·순연 경기도 잔여경기에 포함한다.
- KT–삼성 잔여 맞대결은 하나의 경기 샘플만 생성해 양 팀 결과에 동시에 반영한다.
- `official`, `estimated`, `manual`, `stale` provenance를 입력·출력에 보존한다.
- `TYPESAFE_API_KEY`를 코드·설정 파일·결과 아티팩트에 기록하지 않는다.
- Base/Jev 기본 결합 가중치는 각각 0.60/0.40이며 config/CLI에서 변경 가능하다.
- Monte Carlo 기본 횟수는 1,000,000회이며 명시적 seed로 재현 가능해야 한다.
- Jev는 최종 우승확률을 생성하지 않고 경기별 소판단만 반환한다.
- 공식 데이터가 최신 결과를 반영하지 않으면 `--allow-stale` 없이는 실행을 거부한다.

## Review Focus

- 날짜 미정 순연 경기: 날짜가 없어도 잔여경기 수·최종 승수에는 포함되어야 한다. `test_undated_postponement_counts_as_remaining`에서 고정한다.
- KT–삼성 맞대결: 같은 경기 결과가 양 팀에 반대 방향으로 한 번만 반영되어야 한다. `test_head_to_head_is_sampled_once`에서 고정한다.
- Jev 장애: API 키 없음·timeout·범위 밖 응답이 Base-only fallback으로 명시적 상태를 남겨야 한다. `test_jev_failure_is_audited_and_uses_base`에서 고정한다.
- 공동 1위: 두 팀의 결정전 승률로 단독 1위가 정해지고 공동 상태도 별도 집계되어야 한다. `test_tiebreak_resolves_co_champion`에서 고정한다.
- stale 공식 스냅샷: `--allow-stale` 없이 실행이 실패하고, 허용 시 경고와 manifest가 남아야 한다. `test_stale_snapshot_requires_explicit_flag`에서 고정한다.

## File Map

### Source

- Create `pyproject.toml`: package metadata, dependencies, CLI entry point, pytest/ruff settings.
- Create `README.md`: installation, data provenance, configuration, Jev setup, real-data run and output interpretation.
- Create `config/default.toml`: season, as-of, simulations, seed, weights, stale policy, data source and Jev timeout.
- Create `src/kt_championship_engine/__init__.py`: package version.
- Create `src/kt_championship_engine/__main__.py`: `python -m kt_championship_engine` dispatch.
- Create `src/kt_championship_engine/config.py`: typed TOML configuration and CLI override resolution.
- Create `src/kt_championship_engine/schemas.py`: `TeamStanding`, `Game`, `TeamFeatures`, `GameForecast`, `SimulationSummary`, `DataManifest`.
- Create `src/kt_championship_engine/data_io.py`: JSON/CSV snapshot loading and artifact writing.
- Create `src/kt_championship_engine/collectors/kbo.py`: official KBO HTTP fetch and normalized snapshot parser.
- Create `src/kt_championship_engine/validation.py`: schema, 144-game, duplicate-game, result and provenance validation.
- Create `src/kt_championship_engine/features.py`: current/remaining team features and fallback feature quality.
- Create `src/kt_championship_engine/models/base.py`: transparent logistic Base probability.
- Create `src/kt_championship_engine/models/jev.py`: typed Jev HTTP client and deterministic mock client.
- Create `src/kt_championship_engine/models/combine.py`: Jev subjudgment aggregation and Base/Jev combination.
- Create `src/kt_championship_engine/simulation.py`: residual-game sampling, ranking, tiebreaker, magic number and date confirmation.
- Create `src/kt_championship_engine/evaluation.py`: actual-result join and Brier scores.
- Create `src/kt_championship_engine/reporting.py`: Markdown/JSON/CSV report generation.
- Create `src/kt_championship_engine/cli.py`: `collect`, `validate`, `run`, `evaluate` commands.

### Tests and data

- Create `tests/conftest.py`: shared fixture paths, deterministic fake teams, games and features.
- Create `tests/test_schemas.py`: field/range validation.
- Create `tests/test_validation.py`: season invariants, stale and duplicate handling.
- Create `tests/test_models.py`: Base, Jev mock, combination and fallback.
- Create `tests/test_simulation.py`: linked games, rankings, tiebreak, magic number and date probabilities.
- Create `tests/test_evaluation.py`: Brier score and missing actual-result behavior.
- Create `tests/test_cli.py`: command smoke tests and artifact paths.
- Create `data/fixtures/mini_snapshot.json`: small official-style fixture with one undated postponement and one KT–Samsung game.
- Create `data/snapshots/README.md`: snapshot naming, source metadata and stale policy.
- Create `data/results.csv`: empty schema-compatible result join template.

### Task 1: Scaffold contracts and test harness

**Files:**
- Create: `pyproject.toml`, `README.md`, `config/default.toml`
- Create: `src/kt_championship_engine/__init__.py`, `src/kt_championship_engine/__main__.py`, `src/kt_championship_engine/config.py`, `src/kt_championship_engine/schemas.py`
- Create: `tests/conftest.py`, `tests/test_schemas.py`

**Interfaces:**
- Produces `EngineConfig.from_toml(path: Path) -> EngineConfig`.
- Produces `Game.remaining: bool`, `Game.is_head_to_head(team_a: str, team_b: str) -> bool`.
- Produces `validate_probability(value: float, field_name: str) -> float` and Pydantic models used by every later task.

- [ ] **Step 1: Write failing schema tests**

```python
def test_game_with_undated_postponement_is_remaining(game_factory):
    game = game_factory(status="postponed", game_date=None)
    assert game.remaining is True

def test_probability_rejects_out_of_range():
    with pytest.raises(ValueError):
        GameForecast(game_id="g", team="KT", opponent="SSG", base_probability=1.2)
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `pytest tests/test_schemas.py -q`

Expected: collection or assertion failure because package contracts do not exist.

- [ ] **Step 3: Implement minimal typed contracts and config loader**

Implement immutable-enough Pydantic models with explicit enums for `source_type`, `game status`, and `jev_status`. `Game.remaining` returns `status != "final"`; a final game with missing score raises validation. `EngineConfig` validates `simulations > 0`, `0 <= weights <= 1`, weights sum to 1, and `tiebreak_policy == "single_game"`.

- [ ] **Step 4: Run focused tests and full type/import smoke test**

Run: `pytest tests/test_schemas.py -q && python -m kt_championship_engine --help`

Expected: all focused tests pass and CLI help exits 0.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml README.md config src tests
git commit -m "feat: scaffold engine contracts and configuration"
```

### Task 2: Snapshot I/O, KBO collector and validation

**Files:**
- Create: `src/kt_championship_engine/data_io.py`, `src/kt_championship_engine/collectors/__init__.py`, `src/kt_championship_engine/collectors/kbo.py`, `src/kt_championship_engine/validation.py`
- Create: `data/fixtures/mini_snapshot.json`, `data/snapshots/README.md`, `tests/test_validation.py`

**Interfaces:**
- Produces `load_snapshot(path: Path) -> Snapshot` and `save_snapshot(snapshot: Snapshot, path: Path) -> None`.
- Produces `KBOCollector.fetch(as_of: date) -> Snapshot` and `KBOCollector.from_local(path: Path) -> Snapshot`.
- Produces `validate_snapshot(snapshot: Snapshot, *, as_of: datetime, allow_stale: bool) -> ValidationReport`.

- [ ] **Step 1: Write failing validation tests**

```python
def test_undated_postponement_counts_as_remaining(mini_snapshot):
    report = validate_snapshot(mini_snapshot, as_of=AS_OF, allow_stale=True)
    assert report.remaining_counts["KT"] == 2
    assert report.remaining_counts["SS"] == 2

def test_stale_snapshot_requires_explicit_flag(stale_snapshot):
    with pytest.raises(StaleDataError):
        validate_snapshot(stale_snapshot, as_of=AS_OF, allow_stale=False)

def test_head_to_head_has_one_canonical_game_id(mini_snapshot):
    validate_snapshot(mini_snapshot, as_of=AS_OF, allow_stale=True)
    games = [g for g in mini_snapshot.games if {g.away_team, g.home_team} == {"KT", "SS"}]
    assert len({g.game_id for g in games}) == len(games)
```

- [ ] **Step 2: Run tests and verify failures**

Run: `pytest tests/test_validation.py -q`

Expected: missing snapshot loader, collector and validation functions.

- [ ] **Step 3: Implement local I/O and normalization**

Implement JSON serialization with ISO dates and datetimes, preserving `source_uri`, `source_hash`, `as_of`, and `retrieved_at`. The fixture includes all ten team names, a final result, a scheduled game, a postponed undated game, and a KT–SS game represented once with canonical away/home fields.

- [ ] **Step 4: Implement official collector**

Use `httpx.Client` with a user agent and timeout. Parse KBO HTML tables into standings and schedule rows; store the exact response SHA-256 and retrieval time. If official parsing produces no standings or schedule rows, raise `CollectorError` instead of inventing data. Support local snapshot mode for reproducible runs.

- [ ] **Step 5: Implement validation**

Check ten teams, `played == wins + losses + ties`, calculated win percentage, no final game with null score, no duplicate canonical game, `completed + remaining == 144` for every team, and stale cutoff. Return a report containing warnings, errors, remaining counts, official/estimated counts, and `data_manifest` fields.

- [ ] **Step 6: Run tests and commit**

Run: `pytest tests/test_validation.py -q`

Expected: all validation tests pass.

```bash
git add src/kt_championship_engine/data_io.py src/kt_championship_engine/collectors src/kt_championship_engine/validation.py data tests/test_validation.py
git commit -m "feat: add snapshot collection and validation"
```

### Task 3: Features, Base model, Jev adapter and probability combination

**Files:**
- Create: `src/kt_championship_engine/features.py`, `src/kt_championship_engine/models/__init__.py`, `src/kt_championship_engine/models/base.py`, `src/kt_championship_engine/models/jev.py`, `src/kt_championship_engine/models/combine.py`
- Create: `tests/test_models.py`

**Interfaces:**
- Produces `build_team_features(snapshot: Snapshot) -> dict[str, TeamFeatures]`.
- Produces `base_win_probability(game: Game, features: dict[str, TeamFeatures]) -> float`.
- Produces `JevClient.judge(game: Game, features: GameFeatures) -> JevJudgment`.
- Produces `combine_probabilities(base: float, jev: float | None, config: EngineConfig) -> CombinedProbability`.

- [ ] **Step 1: Write failing model tests**

```python
def test_base_probability_home_advantage_is_monotonic(model_features, game):
    home = base_win_probability(game, model_features)
    away_game = game.model_copy(update={"home_team": game.away_team, "away_team": game.home_team})
    away = 1.0 - base_win_probability(away_game, model_features)
    assert home > 0.5
    assert away < home

def test_jev_failure_is_audited_and_uses_base(game_features, game, config):
    result = combine_probabilities(0.63, None, config)
    assert result.value == pytest.approx(0.63)
    assert result.jev_status == "unavailable"

def test_combined_weight_is_configurable(config, game_features):
    result = combine_probabilities(0.60, 0.80, config.model_copy(update={"base_weight": 0.25, "jev_weight": 0.75}))
    assert result.value == pytest.approx(0.75)
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_models.py -q`

Expected: model modules and functions are missing.

- [ ] **Step 3: Implement feature builder and Base model**

Build current win rate, recent-form proxy from the last ten completed games, home/away split, opponent strength, starter/bullpen/fatigue values, and feature quality. Use explicit neutral defaults for absent values. Implement the documented logistic score with stable sigmoid and clip to `[0.01, 0.99]`.

- [ ] **Step 4: Implement Jev client and mock**

Define a typed request schema for five subjudgments: `starter`, `offense`, `bullpen`, `fatigue`, `matchup`. `HttpJevClient` reads only `TYPESAFE_API_KEY`, sends a JSON request, validates each probability in `[0, 1]`, and maps missing key/timeout/HTTP failure/schema failure to `JevJudgment(status=...)`. `MockJevClient` returns deterministic judgments from a supplied mapping for tests.

- [ ] **Step 5: Implement combination**

Aggregate valid Jev subjudgments using config subweights, combine with Base using configured weights, and set effective Jev weight to zero when Jev is unavailable. Preserve per-component judgments and a feature snapshot hash.

- [ ] **Step 6: Run tests and commit**

Run: `pytest tests/test_models.py -q`

Expected: all model and fallback tests pass.

```bash
git add src/kt_championship_engine/features.py src/kt_championship_engine/models tests/test_models.py
git commit -m "feat: add base and Jev probability models"
```

### Task 4: Deterministic simulation, ranking, tiebreak, magic number and date confirmation

**Files:**
- Create: `src/kt_championship_engine/simulation.py`
- Create: `tests/test_simulation.py`

**Interfaces:**
- Produces `simulate(snapshot: Snapshot, forecasts: list[GameForecast], simulations: int, seed: int) -> SimulationResult`.
- Produces `compute_magic_number(standings: list[TeamStanding], remaining: list[Game]) -> MagicNumber`.
- Produces `resolve_first_place(final_standings, *, tiebreak_probability: float, rng) -> FirstPlaceResult`.
- Produces `date_confirmation_probabilities(...) -> list[DateConfirmation]`.

- [ ] **Step 1: Write failing simulation tests**

```python
def test_head_to_head_is_sampled_once(mini_snapshot, forecasts):
    result = simulate(mini_snapshot, forecasts, simulations=2000, seed=7)
    assert result.linked_game_sample_count == 1
    assert result.team_win_totals["KT"].max() - result.team_win_totals["SS"].max() <= 2

def test_tiebreak_resolves_co_champion(equal_final_standings):
    result = resolve_first_place(equal_final_standings, tiebreak_probability=0.70, rng=np.random.default_rng(3))
    assert result.co_champion_count >= result.kt_first_place_count
    assert result.kt_first_place_count + result.ss_first_place_count == result.tiebreak_resolved_count

def test_date_confirmation_probabilities_sum_to_at_most_one(date_result):
    probabilities = date_confirmation_probabilities(date_result)
    assert sum(row.probability for row in probabilities) <= 1.0 + 1e-12
```

- [ ] **Step 2: Run focused tests and verify failure**

Run: `pytest tests/test_simulation.py -q`

Expected: missing simulation functions and result types.

- [ ] **Step 3: Implement one-pass linked-game sampling**

Index forecasts by canonical game ID. For each simulated game, draw one uniform random number. If the game is KT–SS, assign the winner to exactly one team; for other games sample the listed home/away probability. Accumulate wins and ties separately for every team.

- [ ] **Step 4: Implement final ranking and tiebreak**

Compute `wins / (wins + losses)` with ties excluded from denominator. Identify first-place ties. For a KT–SS tie, draw the configured decision-game probability once per simulation. Store KT first, SS first, co-champion-before-tiebreak, and unresolved/unknown counts separately.

- [ ] **Step 5: Implement magic number and date curve**

Use current wins, games remaining, and the closest competitor’s maximum possible final win percentage to calculate the minimum KT wins needed for strict separation. Replay each dated game in chronological batches for each simulation and record the first date KT is sole first; keep undated games in the final result but assign their confirmation date to `unknown`.

- [ ] **Step 6: Run tests, a 10,000-simulation smoke test and commit**

Run: `pytest tests/test_simulation.py -q && python -m kt_championship_engine run --snapshot data/fixtures/mini_snapshot.json --simulations 10000 --seed 7`

Expected: tests pass; summary probabilities are finite, between 0 and 1, and the run reports one linked head-to-head sample.

```bash
git add src/kt_championship_engine/simulation.py tests/test_simulation.py
git commit -m "feat: add deterministic championship simulation"
```

### Task 5: Evaluation and reporting artifacts

**Files:**
- Create: `src/kt_championship_engine/evaluation.py`, `src/kt_championship_engine/reporting.py`, `data/results.csv`
- Create: `tests/test_evaluation.py`, `tests/test_reporting.py`

**Interfaces:**
- Produces `brier_scores(predictions: Iterable[GameForecast]) -> dict[str, float]`.
- Produces `write_run_artifacts(result: SimulationResult, forecasts: list[GameForecast], manifest: DataManifest, output_dir: Path) -> RunArtifacts`.

- [ ] **Step 1: Write failing evaluation/report tests**

```python
def test_brier_scores_are_separated_by_model(scored_forecasts):
    scores = brier_scores(scored_forecasts)
    assert scores["base"] == pytest.approx(0.25)
    assert scores["jev"] == pytest.approx(0.25)
    assert scores["combined"] == pytest.approx(0.25)

def test_report_contains_provenance_and_top_risk(tmp_path, simulation_result, forecasts, manifest):
    artifacts = write_run_artifacts(simulation_result, forecasts, manifest, tmp_path)
    text = artifacts.summary_md.read_text()
    assert "데이터 갱신 시각" in text
    assert artifacts.game_forecasts_csv.exists()
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_evaluation.py tests/test_reporting.py -q`

Expected: missing evaluator and reporter.

- [ ] **Step 3: Implement Brier Score**

For rows with non-null `actual_result`, calculate mean squared error for `base_probability`, `jev_probability`, and `combined_probability`. Exclude unavailable Jev rows from the Jev score and report evaluated row counts. Raise a clear error when no scored rows exist.

- [ ] **Step 4: Implement artifacts**

Write UTF-8 Markdown summary, JSON summary, game forecast CSV, date confirmation CSV, final wins distribution CSV, and data manifest JSON. Rank risk games by `abs(combined_probability - 0.5)` ascending, include the five closest games, and include source type counts, as-of/retrieved times, seed, simulation count and effective weights.

- [ ] **Step 5: Run tests and commit**

Run: `pytest tests/test_evaluation.py tests/test_reporting.py -q`

Expected: all artifact and score tests pass.

```bash
git add src/kt_championship_engine/evaluation.py src/kt_championship_engine/reporting.py data/results.csv tests/test_evaluation.py tests/test_reporting.py
git commit -m "feat: add model evaluation and run reports"
```

### Task 6: CLI integration, README and complete test suite

**Files:**
- Create: `src/kt_championship_engine/cli.py`
- Modify: `src/kt_championship_engine/__main__.py`, `README.md`, `config/default.toml`
- Create: `tests/test_cli.py`

**Interfaces:**
- `collect --as-of YYYY-MM-DD --output PATH`
- `validate --snapshot PATH [--allow-stale]`
- `run --snapshot PATH --simulations N --seed N --output DIR [--no-jev]`
- `evaluate --predictions PATH --results PATH`

- [ ] **Step 1: Write failing CLI smoke tests**

```python
def test_run_command_writes_summary(cli_runner, fixture_snapshot, tmp_path):
    result = cli_runner.invoke(app, ["run", "--snapshot", str(fixture_snapshot), "--simulations", "100", "--seed", "2", "--output", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / "summary.md").exists()

def test_validate_rejects_stale_without_flag(cli_runner, stale_snapshot):
    result = cli_runner.invoke(app, ["validate", "--snapshot", str(stale_snapshot)])
    assert result.exit_code != 0
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_cli.py -q`

Expected: no Typer app commands are registered.

- [ ] **Step 3: Implement CLI orchestration**

Wire config loading, local/official source selection, validation, feature construction, Base/Jev forecasts, simulation, and reporting. Print a concise Korean summary with KT/삼성 probabilities, final-win means, magic number and most likely confirmation date. Ensure `--no-jev` uses `MockJevClient` with explicit `disabled` status.

- [ ] **Step 4: Update README with exact setup and provenance rules**

Document `python -m venv .venv`, `pip install -e .`, `pytest`, `ruff check`, `TYPESAFE_API_KEY`, local snapshot mode, `--allow-stale`, 1,000,000 simulation command, output files and interpretation of estimates versus official records.

- [ ] **Step 5: Run the complete suite and commit**

Run: `pytest -q && ruff check .`

Expected: all tests pass and lint is clean.

```bash
git add src/kt_championship_engine/cli.py src/kt_championship_engine/__main__.py README.md config/default.toml tests/test_cli.py
git commit -m "feat: expose championship engine CLI"
```

### Task 7: Acquire a real 2026 snapshot and execute the requested run

**Files:**
- Create: `data/snapshots/2026-09-20.json`
- Create: `artifacts/run_2026-09-20/` generated outputs
- Modify: `README.md` only if the verified source endpoint or caveat needs documenting

**Interfaces:**
- Consumes `KBOCollector.fetch(as_of=date(2026, 9, 20))` or a manually preserved official response.
- Produces a validated manifest and a complete run summary without exposing API keys.

- [ ] **Step 1: Collect and preserve official source material**

Fetch KBO standings, schedule and results using the collector. Save raw response hashes and source URIs in the snapshot manifest. If a page is not current as of 2026-09-20, retain the older `as_of` and mark the snapshot stale instead of changing its timestamp.

- [ ] **Step 2: Validate all 144-game counts and remaining schedule**

Run: `python -m kt_championship_engine validate --snapshot data/snapshots/2026-09-20.json`

Expected: ten teams, every team has `played + remaining == 144`, undated postponements remain counted, and KT–SS game IDs are unique.

- [ ] **Step 3: Execute the real 1,000,000-run analysis**

Run: `python -m kt_championship_engine run --snapshot data/snapshots/2026-09-20.json --simulations 1000000 --seed 20260920 --output artifacts/run_2026-09-20`

Expected: process completes without memory errors, reports effective Jev status, and writes all six artifact files.

- [ ] **Step 4: Inspect and verify outputs**

Check that KT/삼성 probabilities are in `[0,1]`, their first-place categories sum with non-contenders and unknown/co-champion categories, win distributions have integer support, date probabilities are nonnegative, and summary metadata matches the snapshot manifest.

- [ ] **Step 5: Commit verified snapshot and outputs**

```bash
git add data/snapshots/2026-09-20.json artifacts/run_2026-09-20 README.md
git commit -m "chore: add verified 2026 data run"
```

### Task 8: Final verification and handoff

**Files:**
- Modify: `README.md` if command output or limitations changed after the real run

- [ ] **Step 1: Run all automated checks**

Run: `pytest -q && ruff check . && python -m kt_championship_engine --help`

Expected: zero failures, zero lint errors, CLI help exits 0.

- [ ] **Step 2: Verify reproducibility**

Run the fixture command twice with the same seed and compare `summary.json` and distributions byte-for-byte after normalizing `predicted_at`; the numerical fields must match exactly.

- [ ] **Step 3: Verify no secret leakage**

Run: `rg -n "TYPESAFE_API_KEY|sk-[A-Za-z0-9]|Bearer " artifacts README.md src config data || true`

Expected: only the environment-variable name in documentation/config comments; no key value or authorization header.

- [ ] **Step 4: Commit final verification notes**

```bash
git add README.md
git commit -m "docs: finalize verification and usage notes"
```

