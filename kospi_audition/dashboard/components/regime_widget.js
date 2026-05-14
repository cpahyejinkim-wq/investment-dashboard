function renderRegime(state) {
  const target = document.getElementById("regime-detail");
  const r = state.data.regime;
  if (!r) { target.innerHTML = `<div class="placeholder">regime_data.json 없음</div>`; return; }
  const sub = r.subscores || {};
  target.innerHTML = `
    <div>Score: <strong>${r.score}</strong> → ${r.state}</div>
    <div>Trend ${sub.trend} · Breadth ${sub.breadth} · Vol ${sub.volatility}</div>
    <div>권장 Mode: <strong>${r.recommended_mode}</strong></div>
    <div>weight × ${r.weight_multiplier} · allowed: ${(r.allowed_tiers||[]).join(", ") || "(none)"}</div>
  `;
}
