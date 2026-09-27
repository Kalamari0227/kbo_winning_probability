# Snapshot storage

파일명은 `YYYY-MM-DD.json`으로 지정하고, `manifest.as_of`에는 실제 원자료가 확인된 기준을 기록합니다. `manifest.as_of_precision`이 `date`이면 날짜 단위 원문으로 취급하고, `datetime`이면 시각 단위 cutoff를 그대로 검증합니다. KBO 순위 화면이 날짜만 제공하는 경우 시각은 해당 날짜 00:00 UTC로 보존하며 수집 시각을 원자료 갱신 시각처럼 덮어쓰지 않습니다. 공식 원문이 갱신되지 않았으면 현재 시각으로 덮어쓰지 않고 `stale=true` 또는 이전 `as_of`를 유지합니다. `validate`와 `run`은 `--allow-stale` 없이 stale 스냅샷을 거부하고, 요청 cutoff보다 새로운 스냅샷도 거부합니다. 일정 API의 원본/재편성 행 관계가 명시되지 않은 경우 `game.schedule_identity=inferred`로 표시하고, 공식 source 여부와 별도로 식별 추정 건수를 보고합니다.
