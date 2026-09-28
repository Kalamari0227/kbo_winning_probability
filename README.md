# KT Championship Engine

2026 KBO 정규시즌의 KT Wiz, 삼성 라이온즈, LG 트윈스 최종 순위 확률을 계산합니다. 경기별 Base/Jev 확률은 Python 시뮬레이션에 넣고, Jev에는 시즌 최종 순위를 계산시키지 않습니다.

## 설치 및 Jev 키 설정

Python 3.11 이상과 `uv`가 필요합니다.

```bash
uv sync --extra dev
cp -n .env.example .env
```

`.env`의 `TYPESAFE_API_KEY`에는 Bearer 접두어 없이 키 값만 넣습니다. 앱이 실행될 때 현재 프로젝트의 `.env`를 읽습니다. 셸에 같은 환경 변수가 있으면 셸 값이 우선합니다. `.env`는 `.gitignore`에서 제외됩니다.

키를 설정하지 않아도 실행할 수 있습니다. 이때 Jev API를 호출했다고 표시하지 않고 결과 모드를 `Base-only`로 기록합니다.

## 최신 데이터 수집과 실행

```bash
mkdir -p artifacts/latest
uv run python -m kt_championship_engine collect --output data/snapshots/latest.json
uv run python -m kt_championship_engine validate --snapshot data/snapshots/latest.json
uv run python -m kt_championship_engine run \
  --snapshot data/snapshots/latest.json \
  --config config/default.toml \
  --output artifacts/latest > artifacts/latest/execution.log 2>&1
```

`collect --as-of YYYY-MM-DD`를 생략하면 KBO 순위 화면이 제공하는 최신 기준일을 사용합니다. `manifest.as_of`는 공식 자료 기준일, `retrieved_at`은 실제 수집 시각입니다. 공식 자료 기준일보다 오래된 결과를 새 데이터처럼 덮어쓰지 않습니다.

## 웹 대시보드

로컬 대시보드는 현재 `artifacts/latest` 결과를 보여줍니다. 잔여 경기 표에서 10개 구단별 대진을 필터링하고, 홈·원정 구분, 홈팀 기준 승률, 선발의 확정·예상·미정 상태를 확인할 수 있습니다. 경기 종료 후 페이지의 **데이터 새로고침**을 누르면 공식 KBO snapshot을 다시 수집하고 기본 설정으로 1,000,000회 시뮬레이션을 실행합니다. Jev 키가 있으면 사전 연결 점검 후 경기별 호출을 하고, 없거나 호출이 실패하면 화면에 Base-only 또는 부분 결합 상태를 정확히 표시합니다. 갱신 명령과 결과 로그는 `artifacts/latest/execution.log`에 기록됩니다.

```bash
uv run python -m kt_championship_engine serve --host 127.0.0.1 --port 8765
```

브라우저에서 `http://127.0.0.1:8765`를 엽니다. 페이지는 이 프로세스가 실행 중일 때만 사용할 수 있으며, 정해진 시각에 자동으로 실행되지는 않습니다. `design/variables.css`의 토큰과 `design/DESIGN.md`의 대시보드 확장 규칙을 사용합니다.

### GitHub Pages 배포

저장소의 GitHub Pages 사이트는 Actions가 Python 엔진을 실행해 정적 데이터와 대시보드를 배포합니다. 게시 페이지는 방문 시 마지막 배포 결과를 불러오며, 매일 한국시간 오전 2시 자동 재계산 일정과 데이터 기준 시각·수집 시각을 표시합니다. Actions secret이 있으면 main 브랜치 변경, 매일 한국시간 오전 2시, 수동 `workflow_dispatch`에서 새 공식 결과를 수집하고 Jev 예측과 시뮬레이션을 다시 실행합니다. Secret이 없는 main 브랜치 변경은 마지막 Jev 성공 결과인 `data/pages_seed.json`을 게시합니다.

Jev가 연결되지 않은 결과를 새로 게시하지 않도록 수동·예약 실행에는 저장소 Actions secret `TYPESAFE_API_KEY`가 필요합니다. GitHub 저장소의 **Settings → Secrets and variables → Actions**에서 이 secret을 직접 설정하세요. `.env`와 키 값은 저장소에 포함하지 않습니다. 키 누락, 사전 연결 점검 실패, Jev 성공 경기 0건이면 배포 작업이 실패하고 기존 Pages 데이터가 유지됩니다. 키가 설정되지 않은 첫 배포는 마지막 로컬 실행에서 Jev가 성공한 `data/pages_seed.json`을 사용합니다.

Pages 배포 주소: <https://kalamari0227.github.io/kbo_winning_probability/>. GitHub Actions 예약 실행은 지연될 수 있고, 공개 저장소에서 60일간 저장소 활동이 없으면 GitHub가 예약 workflow를 비활성화할 수 있습니다.

수집기는 공식 [KBO 팀 순위](https://www.koreabaseball.com/Record/TeamRank/TeamRankDaily.aspx), [KBO 일정](https://www.koreabaseball.com/Schedule/Schedule.aspx), 게임센터 API를 읽습니다. 10개 구단 각각 `played + remaining = 144`인지 검증합니다. 날짜 미정 순연 경기도 결과 시뮬레이션과 잔여 경기 수에 포함합니다. 공식 `game_date`는 비워 두고, 일정 확정 시뮬레이션에는 별도의 `estimated_game_date`를 저장합니다. 추정일은 공식 잔여 일정의 마지막 날짜 다음 날부터 배치하며, 같은 구단이 하루 두 경기를 치르지 않게 하고 KT-삼성 맞대결을 우선합니다. 이는 실제 재편성 발표가 아니라, 일정 발표 전 확정일 계산을 위한 추정입니다.

2026년 8월 25일 KBO 발표상 확정 잔여 일정은 10월 7일까지이며, 일부 순연 경기는 포스트시즌 기간에도 열릴 수 있습니다. 따라서 `summary.md`와 `simulation_summary.json`에는 미정 순연 경기의 추정 날짜 범위와 방식을 함께 기록합니다. 날짜별 확률은 공식 편성일과 추정 순연일을 모두 포함해, 각 날짜에 KT가 처음 단독 1위를 확정하는 시뮬레이션 비율로 계산합니다. 분모는 전체 시뮬레이션 수이므로 날짜별 확률의 합은 확정되지 않는 시뮬레이션이 있으면 100%보다 낮을 수 있습니다. 가장 유력한 확정일은 이 날짜별 확률 중 가장 큰 날짜입니다. [KBO 잔여 경기 일정 공지](https://www.koreabaseball.com/MediaNews/Notice/View.aspx?bdSe=12120)

### JEV 연결 사전 점검

Jev를 활성화한 실행은 첫 잔여 경기로 먼저 API 연결과 응답 JSON을 확인합니다. 성공한 첫 응답은 그 경기 예측에 재사용합니다. 사전 점검이 실패하면 추가 Jev 요청을 멈추고, 실제 시도한 호출의 상태와 나머지 `skipped` 상태를 기록합니다.

`game_forecasts.csv`의 `jev_status`는 실제 HTTP 200과 유효한 응답 스키마를 받은 경기만 `ok`로 둡니다. 401 `unauthorized`, 403 `forbidden`, 422 `invalid_request`, 429 `rate_limited`, 529 `overloaded`, 유효하지 않은 200 응답 `invalid_response`를 구분합니다. 호출을 시도했는지는 `jev_call_attempted`와 HTTP 상태 코드로 확인할 수 있습니다.

Jev는 선발, 타선, 불펜, 일정 피로도, 전체 매치업의 경기별 판단만 제공합니다. 확정 선발은 `official`, 이름이 있으나 확정 플래그가 없는 선발은 `estimated`, 자료가 없으면 `unavailable`로 저장합니다. 라인업도 KBO 게임센터 확인 여부에 따라 공식 또는 최근 라인업 기반 예상치로 구분합니다. 피로도는 공식 경기 일정에서 계산한 휴식일과 최근 7일 경기 수입니다. 현재 수집 API가 불펜 투구 사용량을 주지 않아 Jev 입력에서는 불펜 근거를 `unavailable`로 명시합니다.

## 모델과 재현성

`config/default.toml`이 기본값을 관리합니다.

- Base 60%, Jev 40%
- Monte Carlo 1,000,000회
- 고정 난수 seed를 사용해 동일 스냅샷·설정 결과를 재현
- KT-삼성 경기는 한 개의 경기 행에서 결과를 한 번 뽑아 양 팀 승패에 동시에 반영
- 매직넘버와 최종 순위 계산은 deterministic Python 코드에서 수행

가중치는 config에서 변경할 수 있고 합계가 1이 아니면 실행을 거부합니다. Jev 성공이 0건이면 결합 결과로 표시하지 않습니다. 일부 경기만 Jev에 성공하면 결과 모드에 `mixed_base_jev`가 기록됩니다.

KT 단독 추가승 매직넘버는 모든 경쟁팀의 잔여경기를 고려해 KT가 단독 1위가 되는 추가 승수를 계산합니다. KT-삼성 결합 매직넘버는 `145 - (KT 현재 승수 + 삼성 현재 패수)`이며, 결합 기준 동률 수치도 별도로 표시합니다. 날짜별 KT 1위 확정 확률은 공식 일정과 별도 표기된 추정일을 모두 사용합니다. 미정 경기 날짜를 추정해도 동률 타이브레이크 일정처럼 아직 발표되지 않은 절차가 남으면 일부 시뮬레이션은 `unknown`일 수 있습니다.

대시보드의 예상 최종 승수 요약에는 현재 1~5위 팀의 포스트시즌 매직넘버도 표시합니다. 이는 다른 팀의 결과에 기대지 않고 해당 팀의 추가 승리만으로 5위 이내를 확정하는 보수적 기준입니다.

## 산출물

`artifacts/latest/`에 다음 파일을 만듭니다.

- `simulation_summary.json`, `summary.md`: 순위 확률, 예상 승수, 매직넘버, 확정일, Jev 호출 통계와 데이터 시각
- `game_forecasts.csv`: 경기별 Base/Jev/Combined 확률, 호출 상태, 실제 결과와 출처
- `date_confirmation.csv`: 날짜별 KT 1위 확정 확률
- `final_wins_distribution.csv`, `final_rank_distribution.csv`
- `data_manifest.json`: 공식 출처, SHA-256, 기준일, 수집 시각, 데이터 경고
- `execution.log`: 실제 CLI 실행 로그

같은 출력 폴더에서 재실행하면 `game_forecasts.csv`에 경기 예측 이력을 누적합니다. 경기가 끝나면 이전 예측 확률을 유지한 채 공식 `actual_result`와 결과 출처를 붙여 Base/Jev/Combined Brier Score를 계산할 수 있습니다.

```bash
uv run python -m kt_championship_engine evaluate \
  --predictions artifacts/latest/game_forecasts.csv
```

별도 결과 파일을 사용할 수도 있습니다.

```bash
uv run python -m kt_championship_engine evaluate \
  --predictions artifacts/latest/game_forecasts.csv \
  --results data/results.csv
```

## 검증

```bash
uv run pytest -q
uv run ruff check .
```

마지막 실제 실행은 2026-09-26 공식 기준 스냅샷(2026-09-27 13:10 KST 수집)으로 수행했습니다. 1,000,000회 시뮬레이션에서 KT 1위 81.7346%, 삼성 18.2468%, LG 0.0184%였고, 가장 유력한 KT 확정일은 10월 7일(22.7316%)입니다. 미정 순연 경기 10개의 추정일은 10월 8~11일이며, 잔여 53경기 Jev 호출은 53건 성공·실패 0건이었습니다. 세 구단의 최종 1~3위 확률과 날짜별 확정 확률은 `artifacts/latest/simulation_summary.json` 및 `summary.md`를 확인하세요.
