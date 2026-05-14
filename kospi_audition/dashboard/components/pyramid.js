function renderPyramid(state) {
  const tgt = document.getElementById("pyramid-detail");
  const ranking = state.data.ranking[state.mode];
  if (!ranking) { tgt.innerHTML = `<div class="placeholder">데이터 없음</div>`; return; }
  const counts = { S: 0, A: 0, B: 0, C: 0, D: 0 };
  let invested = 0;
  for (const t of ranking.tickers) {
    counts[t.tier] = (counts[t.tier] || 0) + 1;
    if (["S","A","B","C"].includes(t.tier)) invested += (t.weight || 0);
  }
  tgt.innerHTML = `
    <div class="tier-S">S: ${counts.S}</div>
    <div class="tier-A">A: ${counts.A}</div>
    <div class="tier-B">B: ${counts.B}</div>
    <div class="tier-C">C: ${counts.C}</div>
    <div>투자 비중: ${(invested * 100).toFixed(1)}%</div>
    <div>현금: ${((1 - invested) * 100).toFixed(1)}%</div>
  `;
}
