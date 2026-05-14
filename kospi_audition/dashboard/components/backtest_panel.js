function renderBacktest(state) {
  const tbody = document.querySelector("#backtest-table tbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  const bt = state.data.backtest;
  if (!bt || !bt.strategies) {
    tbody.innerHTML = `<tr><td colspan="9" class="placeholder">backtest_results.json 없음 — run_analysis.py --with-backtest 로 생성</td></tr>`;
    return;
  }
  Object.entries(bt.strategies).forEach(([name, m]) => {
    if (Array.isArray(m) || typeof m !== "object" || m == null) return;
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${name}</td>
      <td>${pct(m.cagr)}</td>
      <td>${pct(m.mdd)}</td>
      <td>${num(m.sharpe)}</td>
      <td>${num(m.sortino)}</td>
      <td>${num(m.calmar)}</td>
      <td>${pct(m.monthly_win_rate)}</td>
      <td>${pct(m.annual_turnover)}</td>
      <td>${pct(m.cagr_after_costs)}</td>
    `;
    tbody.appendChild(tr);
  });
}
function pct(v) { return v == null || isNaN(v) ? "-" : (Number(v) * 100).toFixed(1) + "%"; }
function num(v) { return v == null || isNaN(v) ? "-" : Number(v).toFixed(2); }
