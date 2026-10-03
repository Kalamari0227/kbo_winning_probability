# 2026-10-03 로컬 검증

원격 origin: https://github.com/Kalamari0227/kbo_winning_probability.git

빈 위임 workspace 아래 repo/에 별도 clone하여 기존 체크아웃을 건드리지 않았다. 시작 HEAD와 origin/main은 00f5e761650e50c98d35492b129335ac3543172e, 작업 브랜치는 fix/draw-aware-magic-number. AGENTS.md 및 .agents/skills는 이 저장소에 없다. 초기 로컬 단계에서는 Push, PR, merge, 배포를 수행하지 않았다. 이후 공개 대시보드 반영을 별도 승인받았다.

## 공식 결과 및 기준일

[KBO 스코어보드](https://www.koreabaseball.com/schedule/scoreboard.aspx)의 2026-10-03 경기종료 표시와 수집 API를 대조했다.

- KIA 5–4 LG, 두산 4–6 삼성, 롯데 0–5 KT, SSG 1–13 NC, 키움 7–2 한화.
- 공식 cutoff 2026-10-03 (date precision), 수집 2026-10-03 12:08:16 UTC / 21:08:16 KST.
- [공식 순위](https://www.koreabaseball.com/Record/TeamRank/TeamRankDaily.aspx): KT 85승49패4무, 삼성 82승52패3무, LG 75승61패1무. KT 승률 85/134 = .634328…, 삼성 82/134 = .611940…로 공식 표시 .634/.612와 일치한다. 무승부는 승/(승+패) 분모에서 제외한다.
- 잔여 31경기: KT6, 삼성7, LG7, KIA8, 두산5, NC6, SSG6, 롯데8, 한화5, 키움4. 10팀 모두 played+remaining=144 검증 통과.
- 잔여 KT–삼성 맞대결 3경기: 10/7, 10/11, 10/12. 현재 미정 순연일 추정은 0경기다.
- 수집기 경고: 원래/재편성 중복 73행을 16경기 대진 상한으로 조정했으며, retained 일정 식별 추정 행은 30개다. 일정 출처는 공식이지만 식별 가정이 남아 있다.

## 계산 정의와 규정

[KBO 경기운영제도](https://www.koreabaseball.com/Kbo/League/GameManageRule/GameManage.aspx)의 공식 이미지: 팀당144경기, 2팀 1위 동률은 순위결정전; 3팀 이상은 상대 전적 다승, 다득점, 전년도 성적 순이다. 따라서 동률 도달은 우승 확정이 아니다. 기존 모델은 KT–삼성 2팀 동률의 단일경기만 확률적으로 처리하며, 다른 동률은 미해결/fractional credit 제한을 유지한다.

고정 145-(KT승+삼성패)를 제거했다. 결합 수치는 KT 추가승+삼성 추가패의 합이 일정 수치 이상일 때 모든 가능한 배분에서 삼성보다 높은 최종 승률을 보장하는 최소 정수다. 정확한 Fraction 비교를 쓰고, 맞대결은 한 경기에서 양 팀 결과를 함께 반영한다. 맞대결 KT 승은 합계2개, 맞대결 무승부는 양 팀 분모에서 동시에 제외한다. 독립 경기 무승부는 KT패/삼성승으로 바꾼 최악 조건보다 유리하여 보수적 보장을 깨지 않는다. 보장 불가능은 None, 이미 보장되면 0이다. 삼성 이상 승률 기준은 동률을 허용하며 우승 확정을 뜻하지 않는다. 자력 추가승은 모든 경쟁팀을 상대로 하는 별도 보장이다.

Oct1 KT84승49패4무 / 삼성81승52패3무는 기존 잘못된9 대신 결합5, 자력5다. Oct3는 결합4, 자력4다. 향후 무승부 발생 시 최신 전적과 잔여 일정으로 재계산해야 한다.

## 100만회 실행과 비교

기본 설정 Base60/Jev40, simulations=1,000,000, seed=20260920을 유지했다. 첫 별도 체크아웃 계산은 기존 TYPESAFE_API_KEY가 없어 Jev HTTP 호출0, 성공0, 결과 Base-only였다. 추가 확인에서 기존 kt-championship-engine-live 런타임의 기존 인증 구성을 발견했다. 해당 런타임의 원격/HEAD는 같은 저장소와 00f5e761650e50c98d35492b129335ac3543172e이며 clean main이다. 키를 복사·출력·재설정하지 않고 원래 런타임의 .env를 기존 클라이언트가 읽도록 실행했고, 수정 코드 경로와 산출물 폴더만 별도 체크아웃을 지정했다. Base-only 비교 수치는 실제 60/40 결합 결과와 구분한다. 키 생성·노출, 추가 결제, 약관 동의는 없었다.

| 지표 | Oct1 전적 비교 계산 | Oct3 공식 결과 계산 | 변화 |
|---|---:|---:|---:|
| KT 1위 확률 | 92.7037% | 93.2179% | +0.5142%p |
| 삼성 1위 확률 | 7.2963% | 6.7821% | -0.5142%p |
| KT 예상 최종승 | 88.119707 | 88.476729 | +0.357022 |
| 삼성 예상 최종승 | 85.308306 | 85.753528 | +0.445222 |
| LG 예상 최종승 | 79.248598 | 78.624730 | -0.623868 |
| 가장 유력한 단독1위 확정일 | 10/6 (32.0424%) | 10/6 (34.7656%) | 날짜 동일, +2.7232%p |

Oct1 비교는 오늘 수집한 snapshot에서 Oct3 5경기 결과를 되돌린 통제 비교다. 입력 provenance cutoff는 실제 수집일 Oct3를 유지했다. 오늘 수집한 특징/재편성 일정으로 계산했으므로 이전 run 37038771154의 실제 Jev 결과 또는 당시 예측 재현으로 해석할 수 없다. 저장소의 기존 Pages seed도 다른 기준이어서 직접 확률 변화로 비교하지 않았다.

미래 승패 시뮬레이션은 기존 bernoulli_no_ties를 유지한다. 따라서 확률/확정일은 미래 무승부를 확률적으로 샘플링하지 않는 기존 모델의 조건부 추정이다. 매직넘버 계산의 무승부 보수적 검증과 다르다. 날짜 확정은 단독 승률1위 안전 조건이며 발표되지 않은 결정전 날짜를 만들지 않는다.

## 파일과 검증

변경: simulation.py, reporting.py, cli.py, web/dashboard.js, README.md, data/snapshots/latest.json, tests/test_simulation.py, tests/test_cli.py, tests/test_reporting.py, 이 보고서.

65 tests 통과, ruff check 통과, git diff --check 통과. 추가 회귀 검증은 Oct1 데이터5, 모든 승/패/무 81개 결과의 맞대결 연동 exhaustive 대조, 동일 분모의 엄격/동률 구분, 이미 확정/불가능 경우를 포함한다.

로컬 산출물(artifacts는 gitignore): artifacts/oct3/{snapshot.json,simulation_summary.json,summary.md,game_forecasts.csv,date_confirmation.csv,data_manifest.json,validation.json,execution.log} 및 artifacts/oct1-comparison/. 명령은 기존 CLI collect / validate / run --config config/default.toml이며 오늘 산출물이 기존 파일을 덮지 않도록 별도 폴더로 실행했다.


## 독립 리뷰: 합산 조건의 전수 검증

별도 리뷰어가 구현을 읽고 개별 경기 승/패/무를 독립 전수 열거했다. Oct1은 맞대결3+KT독립4+삼성독립5=12경기로 3^12=531,441개, Oct3는 맞대결3+KT독립3+삼성독립4=10경기로 3^10=59,049개다. 맞대결 KT승은 합계2개로 계산한다.

| 기준 | 결과 수 | KT 뒤짐 | 승률 동률 | KT 우위 실패 최대합 | 임계치 이상 반례 |
|---|---:|---:|---:|---:|---:|
| Oct1 | 531441 | 23179 | 8201 | 4 | 0 (합>=5) |
| Oct3 | 59049 | 2053 | 925 | 3 | 0 (합>=4) |

이는 최선 조합 최소치가 아니라 모든 실현 가능한 합산 조합의 충분조건이다. 유리한 미래 무승부가 있으면 합0에서도 삼성보다 높을 수 있으므로 필요조건은 아니다. 어떤 유리한 사건이 몇 개 있었는지만으로 엄격 우위를 보장하기 위한 보수적 임계치다.

경계 반례: Oct1 합4는 맞대결 KT2승1패, KT독립4패, 삼성독립4승1무일 때 양팀86승54패4무로 동률이다. Oct3 합3은 맞대결 KT1승2패, KT독립1승2패, 삼성독립3승1무일 때 양팀87승53패4무로 동률이다. 이 경우 두 팀만 공동 선두라면 공식 1위 결정전이 필요하고 단독1위 확정으로 표시하면 안 된다. 미래 무승부를 모든 경기에서 포함한 전수검사이며, 무승부 미샘플링 Base-only Monte Carlo 확률과는 별도 검증이다.


## 기존 런타임 실제 Jev 60/40 실행

2026-10-03 같은 공식 snapshot, 같은 config 및 seed로 기존 인증 런타임을 통해 1,000,000회 실행을 완료했다. artifacts/oct3-jev/game_forecasts.csv에는 잔여31경기의 jev_call_attempted=True, jev_http_status=200, jev_status=ok가 모두 기록되어 있다. 사전 연결 점검 성공 응답은 첫 경기 예측에 재사용했고 실제 시도31/성공31/실패0이다. configured/effective Jev weight=.4, Base=.6이며 실제 API 확률이 simulation 입력에 사용됐다.

| 지표 | Oct3 Base-only | Oct3 실제 Base60/Jev40 |
|---|---:|---:|
| KT 1위 | 93.2179% | 93.0639% |
| 삼성 1위 | 6.7821% | 6.9361% |
| KT 예상승 | 88.476729 | 88.492273 |
| 삼성 예상승 | 85.753528 | 85.794869 |
| LG 예상승 | 78.624730 | 78.741336 |
| 가장 유력한 확정일 | 10/6 (34.7656%) | 10/6 (33.2191%) |

결합/자력 매직넘버는 확률 모델과 무관한 결정론적 값으로 모두4다. 이 실제 Jev 결과와 이전 run 37038771154의 정확한 차이는 당시 산출물을 가져오지 않았으므로 주장하지 않는다. 앞의 Oct1→Oct3 변화 표는 같은 Base-only 모델·seed의 통제 비교다. 기존 runtime git status는 실행 후에도 clean main이며 키 파일은 읽기만 했다. GitHub workflow와 배포를 실행하지 않았다. 추가 결제나 새 약관이 요구되지 않았고 별도 승인 차단은 남아 있지 않다.

최종 산출물: artifacts/oct3-jev/simulation_summary.json, summary.md, game_forecasts.csv, date_confirmation.csv, data_manifest.json 및 artifacts/oct3-jev-execution.log. 기존 Base-only 및 Oct1 비교 산출물도 각각 별도 폴더에 보존했다.
