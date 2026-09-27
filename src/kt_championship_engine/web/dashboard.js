const TEAM_LABELS = {
  KT: "KT Wiz",
  SS: "삼성 라이온즈",
  LG: "LG 트윈스",
  KI: "KIA 타이거즈",
  DO: "두산 베어스",
  NC: "NC 다이노스",
  LOT: "롯데 자이언츠",
  SSG: "SSG 랜더스",
  HAN: "한화 이글스",
  KIW: "키움 히어로즈",
};
const TEAM_ORDER = ["KT", "SS", "LG"];
const teamFilter = document.querySelector("#team-filter");
const teamFilterEmblem = document.querySelector("#team-filter-emblem");
const dashboardDataConfig = document.querySelector('meta[name="dashboard-data-url"]');
const isPublishedSite = dashboardDataConfig?.dataset.mode === "published";
let dashboardState;

const refreshButton = document.querySelector("#refresh-button");
const refreshLabel = document.querySelector("#refresh-label");
const refreshHint = document.querySelector(".refresh-hint");
const refreshWorkflowLink = document.querySelector("#refresh-workflow-link");
const liveStatus = document.querySelector("#live-status");
const idleRefreshLabel = isPublishedSite ? "게시 결과 확인" : "데이터 새로고침";

if (isPublishedSite) {
  refreshLabel.textContent = idleRefreshLabel;
  refreshHint.textContent = "게시된 결과만 다시 불러옵니다.";
  refreshWorkflowLink.hidden = false;
}

function node(tag, className, content) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (content !== undefined) element.textContent = content;
  return element;
}

function teamEmblem(team) {
  const emblem = node("img", "team-emblem");
  emblem.src = new URL(`assets/teams/${team}.png`, document.baseURI).href;
  emblem.alt = "";
  emblem.width = 64;
  emblem.height = 41;
  emblem.loading = "lazy";
  emblem.decoding = "async";
  emblem.setAttribute("aria-hidden", "true");
  return emblem;
}

function teamIdentity(team, className) {
  const identity = node("span", className);
  identity.append(teamEmblem(team), node("span", "", TEAM_LABELS[team] || team));
  return identity;
}

function renderTeamFilterEmblem() {
  const team = teamFilter.value;
  teamFilterEmblem.replaceChildren();
  teamFilterEmblem.hidden = team === "all";
  if (team !== "all") teamFilterEmblem.append(teamEmblem(team));
}

function percent(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return `${(Number(value) * 100).toFixed(digits)}%`;
}

function compactDate(value) {
  if (!value) return "미정";
  const date = new Date(`${value}T00:00:00`);
  return new Intl.DateTimeFormat("ko-KR", { month: "long", day: "numeric" }).format(date);
}

function dateTime(value) {
  if (!value) return "확인 불가";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function modeLabel(summary) {
  if (!summary.jev_successful_game_count) return "Base-only · Jev 미사용";
  if (summary.forecast_mode === "mixed_base_jev") return "Base + Jev · 일부 경기";
  return "Base + Jev";
}

function showEmpty(container, message) {
  container.replaceChildren(node("p", "empty-state", message));
}

function renderRankings(state) {
  const grid = document.querySelector("#ranking-grid");
  const summary = state.summary;
  grid.replaceChildren();
  for (const team of TEAM_ORDER) {
    const standing = state.standings.find((row) => row.team === team);
    const probabilities = summary.rank_probabilities?.[team] || {};
    const card = node("article", "rank-card");
    const heading = node("div", "rank-card-header");
    heading.append(teamIdentity(team, "team-identity team-name"));
    if (standing) heading.append(node("span", "record-line", `${standing.wins}승 ${standing.losses}패 ${standing.ties}무`));
    card.append(heading);
    if (standing) {
      const source = standing.source_type === "official" ? "공식 순위" : "추정 순위";
      card.append(node("p", "record-line", `잔여 ${standing.remaining}경기 · ${source}`));
    }
    card.append(node("p", "first-probability", percent(probabilities["1"])));
    const ranks = node("div", "rank-subgrid");
    for (const rank of ["2", "3"]) {
      const entry = node("div");
      entry.append(node("span", "", `${rank}위`), node("span", "", percent(probabilities[rank])));
      ranks.append(entry);
    }
    card.append(ranks);
    grid.append(card);
  }
}

function metricCard(label, value, detail = "", team = null) {
  const card = node("article", "metric-card");
  card.append(team ? teamIdentity(team, "team-identity metric-label") : node("span", "metric-label", label));
  card.append(node("span", "metric-value", value));
  card.append(node("span", "metric-detail", detail));
  return card;
}

function renderWins(summary) {
  const grid = document.querySelector("#wins-grid");
  grid.replaceChildren();
  for (const [team, label, key] of [
    ["KT", TEAM_LABELS.KT, "kt_expected_final_wins"],
    ["SS", TEAM_LABELS.SS, "ss_expected_final_wins"],
    ["LG", TEAM_LABELS.LG, "lg_expected_final_wins"],
  ]) {
    grid.append(metricCard(label, Number(summary[key]).toFixed(2), "시뮬레이션 평균", team));
  }
}

function renderMagic(summary) {
  const grid = document.querySelector("#magic-grid");
  const magic = summary.magic_number || {};
  grid.replaceChildren(
    metricCard("KT 단독 추가승 매직넘버", `${magic.strict_wins_needed ?? "—"}승`, "삼성 등 경쟁팀 잔여경기 반영"),
    metricCard("KT·삼성 결합 매직넘버", `${magic.combined_magic_number ?? "—"}`, "KT 승리와 삼성 패배 결합 기준"),
    metricCard("가장 유력한 확정일", compactDate(summary.most_likely_confirmation_date), percent(summary.most_likely_confirmation_probability)),
  );
}

function renderConfirmation(summary) {
  const rows = summary.date_confirmation_probabilities || [];
  const list = document.querySelector("#date-list");
  const highlight = document.querySelector("#date-highlight");
  const note = document.querySelector("#confirmation-note");
  list.replaceChildren();
  highlight.replaceChildren();
  if (!rows.length) {
    showEmpty(list, "확정일을 계산할 수 있는 잔여 일정이 없습니다.");
    return;
  }
  const best = summary.most_likely_confirmation_date;
  const bestRow = rows.find((row) => row.date === best);
  highlight.append(
    node("span", "metric-label", "가장 가능성 높은 날짜"),
    node("span", "metric-value", compactDate(best)),
    node("span", "metric-detail", `${percent(bestRow?.probability)} 확정 확률`),
  );
  note.textContent = `기준 ${rows.length}개 날짜`;
  const maxValue = Math.max(...rows.map((row) => row.probability), 0.0001);
  for (const row of rows) {
    const line = node("div", "date-row");
    line.append(node("span", "", compactDate(row.date)));
    const bar = node("progress", "date-bar");
    bar.max = maxValue;
    bar.value = row.probability;
    bar.setAttribute("aria-label", `${compactDate(row.date)} KT 1위 확정 확률 ${percent(row.probability)}`);
    line.append(bar, node("span", "date-row-value", percent(row.probability)));
    list.append(line);
  }
}

function jevStatusLabel(status) {
  const labels = {
    ok: "성공",
    unauthorized: "401 인증 실패",
    forbidden: "403 권한 거부",
    rate_limited: "호출 제한",
    invalid_response: "응답 형식 오류",
    invalid_request: "요청 오류",
    overloaded: "서버 과부하",
    http_error: "HTTP 오류",
    skipped: "호출 생략",
    unavailable: "사용 불가",
    disabled: "미사용",
    not_applicable: "해당 없음",
  };
  return labels[status] || status || "확인 불가";
}

function gameProbabilityHeading(summary) {
  if (!summary.jev_successful_game_count) return "Base-only";
  if (summary.forecast_mode === "mixed_base_jev") return "Combined / Base-only";
  return "Combined";
}

function probabilityForTeam(game, probability, selectedTeam) {
  if (selectedTeam === "all" || game.home_team === selectedTeam || probability === null || probability === undefined) {
    return probability;
  }
  return 1 - probability;
}

function renderGames(state) {
  const body = document.querySelector("#games-table-body");
  const games = state.remaining_games || [];
  const selectedTeam = teamFilter.value;
  const visibleGames = selectedTeam === "all"
    ? games
    : games.filter((game) => game.home_team === selectedTeam || game.away_team === selectedTeam);
  body.replaceChildren();
  renderTeamFilterEmblem();
  document.querySelector("#combined-heading").textContent = gameProbabilityHeading(state.summary);
  const probabilityBasis = selectedTeam === "all" ? "홈팀 승률" : "선택팀 승리 확률";
  document.querySelectorAll(".probability-basis").forEach((detail) => {
    detail.textContent = probabilityBasis;
  });
  document.querySelector("#game-probability-note").textContent = selectedTeam === "all"
    ? "전체 구단 보기에서는 각 경기의 홈팀 승률을 표시합니다. 원정팀 승률은 100%에서 홈팀 승률을 뺀 값입니다."
    : `${TEAM_LABELS[selectedTeam]}의 승리 확률을 표시합니다. 선택 팀이 원정이면 100%에서 홈팀 승률을 뺍니다.`;
  let countLabel = `전체 ${games.length}경기`;
  if (selectedTeam !== "all") {
    const probabilities = visibleGames
      .map((game) => probabilityForTeam(game, game.combined_probability, selectedTeam))
      .filter((probability) => probability !== null && probability !== undefined && !Number.isNaN(Number(probability)));
    const expectedWins = probabilities.reduce((total, probability) => total + Number(probability), 0);
    let estimate = "확률 정보 없음";
    if (!visibleGames.length) {
      estimate = "잔여 경기 없음";
    } else if (probabilities.length === visibleGames.length) {
      estimate = `${visibleGames.length}경기 중 예상 ${expectedWins.toFixed(1)}승`;
    } else if (probabilities.length) {
      estimate = `예상 ${expectedWins.toFixed(1)}승 · 확률 ${probabilities.length}/${visibleGames.length}경기 기준`;
    }
    countLabel = `${TEAM_LABELS[selectedTeam]} · 잔여 ${estimate} · 전체 ${games.length}경기`;
  }
  document.querySelector("#remaining-count").textContent = countLabel;
  if (!visibleGames.length) {
    const row = node("tr");
    const cell = node("td", "empty-state", "선택한 구단의 잔여 경기가 없습니다.");
    cell.colSpan = 8;
    row.append(cell);
    body.append(row);
    return;
  }
  for (const game of visibleGames) {
    const row = node("tr");
    row.append(node("td", "", `${compactDate(game.date)}${game.date_status === "estimated" ? " 추정" : ""}`));
    row.append(node("td", "", game.venue || "미정"));
    const matchup = node("td");
    const matchupDetails = node("div", "matchup-cell");
    matchupDetails.append(
      matchupTeam(game.home_team, "홈"),
      matchupTeam(game.away_team, "원정"),
    );
    matchup.append(matchupDetails);
    row.append(matchup);
    const starters = node("td");
    const starterDetails = node("div", "starter-cell");
    starterDetails.append(
      starterLine(game.home_starter, "홈"),
      starterLine(game.away_starter, "원정"),
    );
    starters.append(starterDetails);
    row.append(starters);
    row.append(node("td", "", percent(probabilityForTeam(game, game.base_probability, selectedTeam))));
    row.append(node("td", "", percent(probabilityForTeam(game, game.jev_probability, selectedTeam))));
    row.append(node("td", "", percent(probabilityForTeam(game, game.combined_probability, selectedTeam))));
    row.append(node("td", "", jevStatusLabel(game.jev_status)));
    body.append(row);
  }
}

function matchupTeam(team, side) {
  const entry = node("span", "matchup-team");
  entry.append(node("span", "matchup-side", side), teamIdentity(team, "team-identity matchup-team-label"));
  return entry;
}

function starterLine(starter, side) {
  const status = starter?.status || "unavailable";
  const statusLabels = { official: "확정", estimated: "예상", unavailable: "미정" };
  const line = node("span", "starter-line");
  line.append(node("span", "starter-side", side), node("span", "starter-name", starter?.name || "미정"));
  if (status !== "unavailable") line.append(node("span", "starter-status", statusLabels[status] || "미정"));
  return line;
}

function renderData(state) {
  const { summary, snapshot_manifest: manifest } = state;
  const grid = document.querySelector("#data-grid");
  grid.replaceChildren(
    metricCard("Jev 호출 성공 경기", `${summary.jev_successful_game_count}경기`, `실패 ${summary.jev_failed_call_count}경기 · Base-only ${summary.base_only_game_count}경기`),
    metricCard("데이터 기준시각", dateTime(summary.data_as_of), summary.data_source_type === "official" ? "공식 KBO 기준" : "기준 출처 확인 필요"),
    metricCard("데이터 수집시각", dateTime(summary.data_retrieved_at), `순연 경기 추정 일정 ${summary.estimated_makeup_date_count}건`),
  );
  const method = summary.estimated_schedule_method ? "정규시즌 종료 후 하루 한 경기, KT·삼성 맞대결 우선 배치" : "추정 일정 없음";
  const stale = summary.data_stale ? "현재 결과는 오래된 데이터입니다." : "";
  const source = manifest?.source_type === "official" ? "공식 snapshot" : "snapshot 출처 확인 필요";
  document.querySelector("#data-note").textContent = [source, stale, `추정 일정 방식: ${method}`].filter(Boolean).join(" · ");
}

function render(state) {
  dashboardState = state;
  const summary = state.summary;
  document.querySelector("#simulation-count").textContent = `SIMULATION · ${Number(summary.simulations).toLocaleString("ko-KR")}회`;
  document.querySelector("#forecast-mode").textContent = modeLabel(summary);
  renderRankings(state);
  renderWins(summary);
  renderMagic(summary);
  renderConfirmation(summary);
  renderGames(state);
  renderData(state);
}

async function loadSummary() {
  const endpoint = new URL(dashboardDataConfig?.content || "/api/summary", document.baseURI);
  if (isPublishedSite) endpoint.searchParams.set("refresh", String(Date.now()));
  const response = await fetch(endpoint, { cache: "no-store" });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "최신 결과를 불러오지 못했습니다.");
  render(payload);
  liveStatus.textContent = `현재 산출물 · 수집 ${dateTime(payload.summary.data_retrieved_at)}`;
  return payload;
}

async function refresh() {
  refreshButton.disabled = true;
  refreshButton.setAttribute("aria-busy", "true");
  refreshLabel.textContent = isPublishedSite ? "게시 결과 확인 중" : "공식 결과 수집 및 재계산 중";
  liveStatus.textContent = isPublishedSite
    ? "GitHub Pages에 게시된 최신 결과를 불러오고 있습니다."
    : "KBO 공식 자료를 수집하고 1,000,000회 시뮬레이션을 실행하고 있습니다.";
  try {
    if (isPublishedSite) {
      const payload = await loadSummary();
      liveStatus.textContent = `게시 결과 확인 완료 · 데이터 수집 ${dateTime(payload.summary.data_retrieved_at)} · ${modeLabel(payload.summary)}`;
    } else {
      const response = await fetch("/api/refresh", { method: "POST", cache: "no-store" });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "갱신에 실패했습니다.");
      render(payload);
      liveStatus.textContent = `갱신 완료 · 데이터 수집 ${dateTime(payload.summary.data_retrieved_at)} · ${modeLabel(payload.summary)}`;
    }
  } catch (error) {
    liveStatus.textContent = `새로고침 실패 · ${error.message}`;
  } finally {
    refreshButton.disabled = false;
    refreshButton.removeAttribute("aria-busy");
    refreshLabel.textContent = idleRefreshLabel;
  }
}

refreshButton.addEventListener("click", refresh);
teamFilter.addEventListener("change", () => {
  if (dashboardState) renderGames(dashboardState);
});
loadSummary().catch((error) => {
  liveStatus.textContent = `최신 결과를 불러오지 못했습니다 · ${error.message}`;
});
