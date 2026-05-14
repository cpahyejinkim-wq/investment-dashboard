function renderLeaderboard(state) {
  const tbody = document.querySelector("#leaderboard tbody");
  tbody.innerHTML = "";
  const ranking = state.data.ranking[state.mode];
  if (!ranking) return;
  const filtered = ranking.tickers.filter((t) => {
    if (state.filters.tier !== "all" && t.tier !== state.filters.tier) return false;
    if (state.filters.market !== "all" && t.market !== state.filters.market) return false;
    return true;
  });
  filtered.slice(0, 100).forEach((t, i) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${i + 1}</td>
      <td class="tier-${t.tier}">${t.tier}</td>
      <td>${t.ticker}</td>
      <td>${t.market || "-"}</td>
      <td>${fmt(t.mode_score)}</td>
      <td>${fmtPct(t.rs_20d)}</td>
      <td>${fmtPct(t.rs_60d)}</td>
      <td>${fmt(t.acceleration_pct)}</td>
      <td>${t.rank_velocity_5d ?? "-"}</td>
      <td>${fmtPct(t.weight, 1)}</td>
      <td>${t.stop_loss ?? "-"}</td>
    `;
    tbody.appendChild(tr);
  });
}
function fmt(v, digits = 1) { return v == null || isNaN(v) ? "-" : Number(v).toFixed(digits); }
function fmtPct(v, digits = 1) { return v == null || isNaN(v) ? "-" : (Number(v) * 100).toFixed(digits) + "%"; }
