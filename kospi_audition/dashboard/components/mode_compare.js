function renderModeCompare(state) {
  const tgt = document.getElementById("mode-comparison-detail");
  if (!tgt) return;
  const data = state.data.mode_compare;
  if (!data) {
    tgt.innerHTML = `<div class="placeholder">mode_compare.json 없음</div>`;
    return;
  }
  const overlapPct = Math.round((data.overlap_ratio || 0) * 100);
  tgt.innerHTML = `
    <div>Top ${data.top_n} 교집합: <strong>${data.intersection.length}</strong> 종목 (${overlapPct}%)</div>
    <div>건강도: <strong>${data.health}</strong> (30~70% 권장)</div>
    <div style="margin-top:6px;font-size:12px;">
      <div>공통 리더: ${data.intersection.join(", ") || "-"}</div>
      <div>Sprint Only: ${data.sprint_only.slice(0,5).join(", ") || "-"}</div>
      <div>Marathon Only: ${data.marathon_only.slice(0,5).join(", ") || "-"}</div>
    </div>
  `;
}
