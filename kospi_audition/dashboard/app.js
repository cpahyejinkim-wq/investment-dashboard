// Entry point. Loads JSON outputs and dispatches to component renderers.

const STATE = {
  mode: "sprint", // active mode (Stage 1: sprint only)
  data: { regime: null, ranking: {}, risk: null, leaders: null },
  filters: { tier: "all", market: "all" },
};

async function loadJson(name) {
  try {
    const res = await fetch(`../output/${name}`);
    if (!res.ok) return null;
    return await res.json();
  } catch (e) {
    console.warn("load failed", name, e);
    return null;
  }
}

async function refresh() {
  const [regime, sprintRanking, marathonRanking, risk, leaders, compare, positions] = await Promise.all([
    loadJson("regime_data.json"),
    loadJson("ranking_sprint.json"),
    loadJson("ranking_marathon.json"),
    loadJson("risk_alerts.json"),
    loadJson("new_leaders.json"),
    loadJson("mode_compare.json"),
    loadJson("positions.json"),
  ]);
  STATE.data.regime = regime;
  STATE.data.ranking.sprint = sprintRanking;
  STATE.data.ranking.marathon = marathonRanking;
  STATE.data.risk = risk;
  STATE.data.leaders = leaders;
  STATE.data.mode_compare = compare;
  STATE.data.positions = positions;
  if (regime && regime.recommended_mode && regime.recommended_mode !== "cash") {
    initialActiveMode(STATE, regime.recommended_mode);
  }
  render();
}

function render() {
  renderTopBar(STATE);
  renderRegime(STATE);
  renderPyramid(STATE);
  renderLeaderboard(STATE);
  renderNewLeaders(STATE);
  renderRisk(STATE);
  renderModeCompare(STATE);
  renderMigrationNotice(STATE);
}

function renderTopBar(state) {
  const regime = state.data.regime || {};
  document.getElementById("as-of").textContent = regime.as_of || "-";
  document.getElementById("regime-state").textContent = `Regime: ${regime.state || "-"} (${regime.score ?? "-"})`;
  document.getElementById("recommended-mode").textContent = `권장: ${regime.recommended_mode || "-"}`;
  const inds = regime.indicators || {};
  document.getElementById("kospi-close").textContent = inds.kospi_close ? `KOSPI ${inds.kospi_close.toFixed(2)}` : "";
  document.getElementById("vkospi").textContent = inds.vkospi ? `VKOSPI ${inds.vkospi.toFixed(2)}` : "";
  const mismatch = regime.recommended_mode && regime.recommended_mode !== state.mode && regime.recommended_mode !== "cash";
  document.getElementById("mode-mismatch").classList.toggle("hidden", !mismatch);
  const ranking = state.data.ranking[state.mode];
  document.getElementById("universe-size").textContent = ranking ? ranking.universe_size : "-";

  const kpiRow = document.getElementById("kpi-row");
  if (ranking) {
    const counts = { S: 0, A: 0, B: 0, C: 0, D: 0 };
    for (const t of ranking.tickers) counts[t.tier] = (counts[t.tier] || 0) + 1;
    kpiRow.innerHTML = `
      <div class="kpi"><div class="label">Mode</div><div class="value">${ranking.mode.toUpperCase()}</div></div>
      <div class="kpi"><div class="label">S Tier</div><div class="value">${counts.S}</div></div>
      <div class="kpi"><div class="label">A Tier</div><div class="value">${counts.A}</div></div>
      <div class="kpi"><div class="label">B Tier</div><div class="value">${counts.B}</div></div>
      <div class="kpi"><div class="label">Breadth</div><div class="value">${(inds.breadth_above_ma20 ?? 0).toFixed(2)}</div></div>
    `;
  } else {
    kpiRow.innerHTML = `<div class="placeholder">${state.mode}용 ranking_${state.mode}.json 이 아직 생성되지 않았습니다.</div>`;
  }
}

document.getElementById("filter-tier").addEventListener("change", (e) => {
  STATE.filters.tier = e.target.value;
  renderLeaderboard(STATE);
});
document.getElementById("filter-market").addEventListener("change", (e) => {
  STATE.filters.market = e.target.value;
  renderLeaderboard(STATE);
});

initModeToggle(STATE, render);
refresh();
