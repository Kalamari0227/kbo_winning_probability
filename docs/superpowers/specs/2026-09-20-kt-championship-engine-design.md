# KT Championship Engine v0.1 설계 명세

## 1. 목적과 범위

KT Championship Engine은 2026 KBO 정규시즌에서 KT Wiz와 삼성 라이온즈의 1위 경쟁을 경기 단위 확률과 Monte Carlo 시뮬레이션으로 분석하는 실행 가능한 Python CLI 프로젝트다.

v0.1의 산출물은 다음을 포함한다.

- KBO 공식 순위·일정·완료 결과의 수집 및 불변식 검증
- 팀당 정규시즌 144경기 기준 잔여경기 계산
- 취소·순연됐으나 날짜가 확정되지 않은 경기의 잔여경기 포함
- KT–삼성 잔여 맞대결의 단일 경기 샘플링
- 경기별 Base probability, Jev probability/judgment, Combined probability, 실제 결과 저장
- Base 60% + Jev 40%의 설정 가능한 결합 모델
- 1,000,000회 기본 Monte Carlo
- KT·삼성 단독 1위 확률, 예상 최종 승수 분포, 매직넘버, 날짜별 확정확률, 위험 경기 TOP 5
- 향후 결과 누적 시 Base/Jev/Combined Brier Score 평가

v0.1은 예측을 공식 기록으로 대체하지 않는다. 공식으로 확인된 값과 추정·수동 입력은 모든 레코드에 별도 provenance를 가진다.

## 2. 성공 기준

다음 조건을 모두 만족해야 v0.1 완료로 본다.

1. 신규 환경에서 README의 설치·실행 절차만으로 테스트와 모의 실행을 통과한다.
2. 실제 2026 데이터 스냅샷으로 최소 1회 전체 실행이 가능하다.
3. 팀별 완료 경기 + 잔여 경기 = 144이며, 일정의 KT–삼성 맞대결은 두 팀에서 동일한 경기 ID를 공유한다.
4. 공식 데이터가 갱신되지 않은 경우 수집 시각을 갱신 시각으로 가장하지 않고, 이전 스냅샷을 `stale`로 표시한다.
5. Jev 키가 없거나 호출에 실패해도 시뮬레이션 자체는 재현 가능하게 실행되며, Jev 미사용 사실이 결과와 로그에 남는다.
6. 같은 seed·동일 입력은 동일한 결과를 재생산한다.

## 3. 용어와 승률 규칙

- `official`: KBO 공식 페이지/API에서 직접 확인한 값.
- `estimated`: 공개 자료나 모델로 추정한 값. 실제 기록으로 취급하지 않는다.
- `manual`: 사용자가 직접 입력한 값.
- `stale`: 마지막 공식 확인 이후 `as_of` 기준을 충족하지 못한 스냅샷.
- `as_of`: 분석에 반영할 기준 시각.
- 승률은 KBO 순위 표기 관행인 `승 / (승 + 패)`를 기본으로 한다. 무승부는 승·패에 포함하지 않는다.
- 정규시즌 최종 승수 분포는 승리 횟수만 집계하고 무승부는 별도 분포로 보존한다.
- KT와 삼성이 승률 공동 1위가 되면, v0.1은 두 팀의 단독 1위 결정전을 추가 경기로 모델링한다. 결정전 승률은 두 팀의 마지막 Combined probability를 기본값으로 사용하되 설정으로 별도 지정할 수 있다.
- 결정전이 실행되는 경우에만 KT 또는 삼성을 단독 정규시즌 1위로 집계한다. 결정전 전 공동 1위 상태는 별도 `co_champion_before_tiebreak` 지표로 기록한다.

## 4. 시스템 구조

```text
KBO official pages / snapshots
              |
        collectors + validation
              |
   normalized standings/schedule/results
              |
       feature builder + provenance
          /                    \
 Base statistical model       Jev adapter
          \                    /
          probability combiner
                  |
          deterministic simulator
                  |
      summaries + audit artifacts
                  |
          Brier score evaluator
```

### 4.1 모듈 경계

- `kt_championship_engine.schemas`: Pydantic/dataclass 기반 입력·출력 계약.
- `kt_championship_engine.collectors`: KBO 공식 자료 수집, HTTP 캐시, 스냅샷 메타데이터.
- `kt_championship_engine.validation`: 일정·순위·결과 불변식 및 stale 판정.
- `kt_championship_engine.features`: 팀/경기 특성 생성과 공식·추정값 분리.
- `kt_championship_engine.models.base`: 통계적 Base probability 계산.
- `kt_championship_engine.models.jev`: Jev 호출, 응답 검증, timeout/retry/circuit-breaker.
- `kt_championship_engine.models.combine`: logit 또는 확률 공간 결합과 clip.
- `kt_championship_engine.simulation`: 경기 결과 샘플링, 순위·동률·날짜별 확정 계산.
- `kt_championship_engine.evaluation`: 결과 join과 Brier Score.
- `kt_championship_engine.cli`: `collect`, `run`, `evaluate`, `validate` 명령.

모듈은 파일·HTTP·Jev 네트워크 의존성을 주입할 수 있어 단위 테스트에서 fake collector와 fake Jev를 사용할 수 있어야 한다.

## 5. 데이터 계약과 provenance

### 5.1 Standings

필수 필드: `season`, `team_id`, `team_name`, `played`, `wins`, `losses`, `ties`, `win_pct`, `rank`, `as_of`, `retrieved_at`, `source_type`, `source_uri`, `source_hash`.

검증:

- `played == wins + losses + ties`
- `win_pct`가 원자료에 있을 경우 계산값과 허용 오차 내 일치
- 10개 KBO 팀 전체 존재 여부 확인
- `retrieved_at`보다 미래인 `as_of` 금지

### 5.2 Games

필수 필드: `game_id`, `season`, `game_date`(미정이면 null), `status`(`scheduled`, `postponed`, `cancelled`, `final`), `away_team`, `home_team`, `away_score`, `home_score`, `is_official_result`, `source_type`, `as_of`, `retrieved_at`.

완료 경기만 실제 결과를 가진다. 날짜 미정 취소·순연 경기는 `game_date=null`로 유지하고 잔여경기 수에 포함한다. 일정 화면에 같은 경기가 중복 노출되면 `game_id`와 팀·일자·구장 조합으로 deduplicate한다.

### 5.3 Game forecast audit

각 경기마다 다음을 저장한다.

`game_id`, `team`, `opponent`, `is_home`, `base_probability`, `jev_probability`, `combined_probability`, `jev_status`, `feature_snapshot_hash`, `actual_result`, `result_source`, `predicted_at`.

예측 시점에 실제 결과가 없으면 `actual_result=null`이다. 나중에 결과가 확인되면 원 예측 레코드를 덮어쓰지 않고 결과 join 또는 versioned update로 채운다.

## 6. 데이터 수집·검증 전략

공식 KBO 순위와 경기일정을 1차 출처로 사용한다. 공식 페이지가 동적이거나 일시적으로 접근 불가하면 수집 실패를 명시하고, 사용자가 제공한 스냅샷 또는 저장된 공식 스냅샷을 `stale`로만 사용할 수 있다. 자동화가 임의로 과거값의 `retrieved_at`을 현재 시각으로 갱신하지 않는다.

수집기는 다음을 지원한다.

- HTTP 공식 페이지 수집 및 원문 hash 저장
- 로컬 JSON/CSV 스냅샷 수집
- 입력 데이터의 `as_of` 컷오프 적용
- 144경기 불변식 검증
- 완료 경기 결과와 일정의 교차 검증
- 취소·순연·미정 날짜 경기 포함 검증
- KT–삼성 경기의 단일 `game_id` 연동 검증

공식 데이터가 최신 결과를 반영하지 않는 것이 확인되면 실행을 중단하거나 `--allow-stale`를 명시해야 한다. `--allow-stale` 사용 시 보고서 상단에 경고를 표시한다.

## 7. 경기 확률 모델

### 7.1 Base model

v0.1 Base probability는 설명 가능한 로지스틱 점수로 시작한다.

```text
logit(p_base) = intercept
              + home_advantage
              + team_strength_diff
              + recent_form_diff
              + starter_diff
              + bullpen_diff
              + fatigue_diff
              + schedule_adjustment
```

각 특성은 입력이 없을 때 중립값 0으로 대체하고, 대체 사실을 feature quality에 기록한다. 공개 공식 팀 지표를 사용할 수 없는 항목은 `estimated` 또는 `manual` 입력으로만 채운다.

### 7.2 Jev decomposition

Jev에게 한 번에 우승확률을 묻지 않는다. 경기별로 다음 다섯 판단을 별도 요청한다.

1. 선발투수 우위
2. 타선 우위
3. 불펜 상태
4. 일정·피로 영향
5. 전체 매치업 우위

각 판단은 0~1의 KT 승리 확률 또는 명시된 방향의 adjustment와 confidence를 반환한다. 응답 schema·범위를 검증하고, 범위 밖 값이나 비정상 응답은 해당 판단을 결측 처리한다. 다섯 판단은 설정된 가중치로 `p_jev`를 만든다.

Jev 요청 payload에는 분석 기준일, 상대, 홈/원정, 선발 식별자·최근 지표, 타선/불펜 지표, 휴식일, 데이터 provenance를 포함하되 API 키나 불필요한 개인정보는 포함하지 않는다.

### 7.3 결합

기본값은 `base_weight=0.60`, `jev_weight=0.40`이다. 결합은 확률을 직접 평균하되 극단값을 `epsilon`으로 clip한다.

```text
p_combined = clip(base_weight * p_base + jev_weight * p_jev, 0.01, 0.99)
```

두 가중치 합은 1이어야 하며 설정 파일에서 변경 가능하다. Jev가 unavailable이면 실행별 정책에 따라 `p_combined=p_base`로 계산하고 `jev_weight_effective=0`을 기록한다.

## 8. Monte Carlo와 1위 판정

기본 시뮬레이션 횟수는 1,000,000회이며 CLI에서 조정할 수 있다. NumPy Generator와 명시적 seed를 사용한다.

한 시뮬레이션에서 모든 잔여 경기를 순회한다. KT–삼성 경기는 하나의 Bernoulli/다항 샘플을 생성해 승자 한 팀에만 결과를 반영한다. 동일 경기의 KT와 삼성 확률을 독립 샘플링하지 않는다.

전체 리그 순위 산출을 위해 전체 잔여 일정이 있으면 모든 팀 경기를 시뮬레이션한다. KT·삼성 이외 경기의 세부 전력이 없으면 팀별 현재 승률·홈 보정 기반의 fallback probability를 사용하고 `estimated_fallback`으로 표시한다. 분석 보고서에는 KT·삼성 경기에 적용한 상세 확률과 다른 경기 fallback 비율을 함께 표시한다.

최종 순위는 승률, 승·패 집계, 동률 집합을 기준으로 계산한다. KT 또는 삼성이 공동 1위 집합에 들어가면 설정된 결정전 확률로 단독 1위를 결정한다. 두 팀이 동시에 공동 1위가 아닌 경우에는 실제 공동 1위 규칙을 적용할 수 있도록 `tiebreak_policy` 인터페이스를 둔다.

### 8.1 날짜별 확정확률

경기 날짜가 있는 잔여경기를 시간순으로 적용하면서 각 날짜의 종료 상태를 확인한다. 날짜 미정 경기는 확정일을 알 수 없으므로 기본 날짜별 확정확률 표에서는 제외하고, “미정 경기 포함 최종 확률”에는 포함한다. 같은 날짜의 경기는 해당 날짜 종료 후 한 번에 판정한다.

`P(KT confirmed on date d)`는 `KT가 d 이전에는 단독 1위가 아니고 d 종료 후 단독 1위`인 시뮬레이션 비율이다. 가장 유력한 확정일은 이 값이 최대인 날짜이며, 미정 경기로 인해 확정일이 `unknown`이 되는 비율도 별도 출력한다.

### 8.2 매직넘버

현재 매직넘버는 잔여경기와 경쟁팀의 최선·최악 조합을 고려해 KT가 단독 1위를 보장하는 데 필요한 KT 승리 수로 계산한다. 공동 1위 결정전 정책이 적용되는 경우에는 결정전에서 KT가 이기는 조건까지 포함한 `strict_magic_number`를 함께 기록한다.

## 9. 출력물

실행 디렉터리 아래에 다음을 생성한다.

- `artifacts/run_<timestamp>/summary.md`
- `artifacts/run_<timestamp>/summary.json`
- `artifacts/run_<timestamp>/game_forecasts.csv`
- `artifacts/run_<timestamp>/date_confirmation.csv`
- `artifacts/run_<timestamp>/final_wins_distribution.csv`
- `artifacts/run_<timestamp>/data_manifest.json`

요약에는 KT/삼성 단독 1위 확률, 예상 최종 승수와 분위수, 현재 매직넘버, 가장 유력한 확정일, 날짜별 확정확률, 위험 경기 TOP 5, 데이터 갱신 시각, 공식/추정 입력 비율, 모델 전제를 포함한다.

## 10. Jev API와 보안

- API 키는 코드·config·아티팩트에 저장하지 않는다.
- 환경변수 이름은 `TYPESAFE_API_KEY`로 고정한다.
- endpoint와 model은 `TYPESAFE_JEV_ENDPOINT`, `TYPESAFE_JEV_MODEL`로 선택 가능하되 기본값은 문서화한다.
- timeout, retry, 응답 schema 검증, 요청 hash, 상태(`ok`, `unavailable`, `invalid`, `rate_limited`)를 기록한다.
- API 호출이 불가능한 오프라인 테스트용 `MockJevClient`를 제공한다.

## 11. 테스트 전략

단위 테스트:

- standings/game schema 및 144경기 불변식
- 취소·순연 미정 경기의 잔여 포함
- 중복 일정 deduplication
- KT–삼성 동일 game_id 단일 샘플링
- 확률 결합 가중치·clip·Jev unavailable fallback
- 매직넘버 경계값
- 동률 결정전 승자 배분
- 날짜별 확정확률의 합과 unknown 처리
- Brier Score 계산

통합 테스트:

- fixture snapshot → validation → model → simulation → artifacts 전체 흐름
- 같은 seed의 결과 재현
- malformed Jev 응답과 timeout

실제 데이터 검증:

- 공식 2026 스냅샷을 사용해 최소 1회 실행
- 실행 로그와 `data_manifest.json`에서 source URI/hash, as_of, retrieved_at 확인
- 1,000,000회 실행을 별도 smoke/performance 명령으로 완료하고 출력 확률 합이 1에 가까운지 확인

## 12. CLI와 설정

```bash
python -m kt_championship_engine collect --as-of 2026-09-20
python -m kt_championship_engine validate --snapshot data/snapshots/latest.json
python -m kt_championship_engine run --as-of 2026-09-20 --simulations 1000000 --seed 20260920
python -m kt_championship_engine evaluate --results data/results.csv
```

`config/default.toml`은 season, simulations, seed, base/jev weights, tiebreak policy, stale policy, data source, Jev timeout을 보유한다. 명령줄 옵션이 config보다 우선한다.

## 13. 명시적 비범위

- 스포츠토토·베팅 추천
- Jev가 직접 최종 우승확률을 생성하는 구조
- 비공식 데이터의 공식 기록 대체
- 선수 개인정보 수집
- 실시간 대시보드/웹 서비스

