"use strict";

const STATE = {
  mode: "sprint",
  regime: null,
  ranking: { sprint: null, marathon: null },
  newLeaders: null,
  sectors: null,
  riskAlerts: null,
  filters: { tier: "", sector: "", market: "" },
};

const fmt = {
  num: (v, d = 1) => v == null || Number.isNaN(v) ? "—" : Number(v).toFixed(d),
  pct: (v, d = 0) => v == null || Number.isNaN(v) ? "—" : (Number(v)).toFixed(d) + "%",
  pctFromUnit: (v) => v == null ? "—" : (Number(v) * 100).toFixed(1) + "%",
  int: (v) => v == null ? "—" : Math.round(Number(v)).toLocaleString(),
  price: (v) => v == null ? "—" : Math.round(Number(v)).toLocaleString(),
};

async function loadJson(path) {
  try {
    const r = await fetch(path + "?ts=" + Date.now());
    if (!r.ok) throw new Error(r.status);
    return await r.json();
  } catch (e) {
    console.warn("Failed to load", path, e);
    return null;
  }
}

async function loadAll() {
  const [regime, rankSprint, rankMarathon, newLeaders, sectors, risk] = await Promise.all([
    loadJson("../output/regime_data.json"),
    loadJson("../output/ranking_sprint.json"),
    loadJson("../output/ranking_marathon.json"),
    loadJson("../output/new_leaders.json"),
    loadJson("../output/sector_data.json"),
    loadJson("../output/risk_alerts.json"),
  ]);
  STATE.regime = regime;
  STATE.ranking.sprint = rankSprint;
  STATE.ranking.marathon = rankMarathon;
  STATE.newLeaders = newLeaders;
  STATE.sectors = sectors;
  STATE.riskAlerts = risk;
}

function renderRegime() {
  const r = STATE.regime;
  if (!r) return;
  document.getElementById("data-as-of").textContent = r.data_as_of || "—";
  document.getElementById("footer-as-of").textContent = r.as_of || "—";
  const stateEl = document.getElementById("regime-state");
  stateEl.textContent = r.state;
  stateEl.className = "regime-pill " + r.state;
  document.getElementById("recommended-mode").textContent = r.recommended_mode;
  document.getElementById("kospi-close").textContent = fmt.int(r.indicators?.kospi_close);
  document.getElementById("vkospi").textContent = fmt.num(r.indicators?.vkospi, 1);
  document.getElementById("regime-score").textContent = (r.score >= 0 ? "+" : "") + r.score;
  document.getElementById("ss-trend").textContent = r.subscores?.trend ?? "—";
  document.getElementById("ss-breadth").textContent = r.subscores?.breadth ?? "—";
  document.getElementById("ss-volatility").textContent = r.subscores?.volatility ?? "—";
  document.getElementById("kpi-entry-allowed").textContent = r.allow_new_entry ? "ON" : "OFF (Risk-Off)";
  document.getElementById("kpi-weight-mult").textContent = "×" + fmt.num(r.weight_multiplier, 1);
  document.getElementById("kpi-breadth").textContent = fmt.pctFromUnit(r.indicators?.breadth_above_ma20);

  const hint = document.getElementById("mode-recommendation");
  if (r.recommended_mode === STATE.mode) {
    hint.textContent = `현재 ${STATE.mode}이 권장 모드입니다.`;
  } else if (r.recommended_mode === "cash") {
    hint.textContent = "Risk-Off — 신규 진입이 차단됩니다.";
  } else {
    hint.textContent = `⚠ Regime은 ${r.recommended_mode}를 권장합니다.`;
  }

  // Mark recommended button
  document.querySelectorAll(".mode-toggle button").forEach(b => {
    b.classList.toggle("recommended", b.dataset.mode === r.recommended_mode);
  });
}

function applyFilters(rows) {
  const f = STATE.filters;
  return rows.filter(t => {
    if (f.tier && t.tier !== f.tier) return false;
    if (f.sector && t.sector !== f.sector) return false;
    if (f.market && t.market !== f.market) return false;
    return true;
  });
}

function renderLeaderboard() {
  const r = STATE.ranking[STATE.mode];
  const body = document.getElementById("leaderboard-body");
  document.getElementById("lb-mode").textContent = STATE.mode.charAt(0).toUpperCase() + STATE.mode.slice(1);
  document.getElementById("kpi-current-mode").textContent = STATE.mode.charAt(0).toUpperCase() + STATE.mode.slice(1);
  document.getElementById("universe-size").textContent = r?.universe_size ?? "—";
  body.innerHTML = "";
  if (!r) return;

  const tickers = applyFilters(r.tickers);
  const top = tickers.slice(0, 40);

  // Pyramid counts
  const counts = { S: 0, A: 0, B: 0, C: 0 };
  r.tickers.forEach(t => { if (counts[t.tier] !== undefined) counts[t.tier]++; });
  document.getElementById("cnt-s").textContent = counts.S;
  document.getElementById("cnt-a").textContent = counts.A;
  document.getElementById("cnt-b").textContent = counts.B;
  document.getElementById("cnt-c").textContent = counts.C;
  document.getElementById("kpi-s").textContent = counts.S;
  document.getElementById("kpi-a").textContent = counts.A;
  document.getElementById("kpi-b").textContent = counts.B;
  const maxC = Math.max(counts.S, counts.A, counts.B, counts.C, 1);
  document.getElementById("bar-s").style.width = (counts.S / maxC * 100) + "%";
  document.getElementById("bar-a").style.width = (counts.A / maxC * 100) + "%";
  document.getElementById("bar-b").style.width = (counts.B / maxC * 100) + "%";
  document.getElementById("bar-c").style.width = (counts.C / maxC * 100) + "%";

  // Sector dropdown
  const sectorSel = document.getElementById("filter-sector");
  if (sectorSel.options.length <= 1) {
    const sectors = [...new Set(r.tickers.map(t => t.sector).filter(Boolean))].sort();
    sectors.forEach(s => {
      const o = document.createElement("option"); o.value = s; o.textContent = s;
      sectorSel.appendChild(o);
    });
  }

  // Rows
  top.forEach((t, i) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${i + 1}</td>
      <td>${t.ticker}</td>
      <td>${t.name || ""}</td>
      <td>${t.sector || ""}</td>
      <td><span class="tier-badge ${t.tier}">${t.tier}</span></td>
      <td>${fmt.num(t.mode_score_pct, 1)}</td>
      <td>${fmt.num(t.leader_score, 1)}</td>
      <td>${fmt.num(t.rank_velocity_pct, 0)}</td>
      <td>${fmt.num(t.acceleration, 0)}</td>
      <td>${fmt.pctFromUnit(t.rs_20d)}</td>
      <td>${fmt.pctFromUnit(t.rs_60d)}</td>
      <td>${fmt.pctFromUnit(t.weight)}</td>
      <td>${fmt.price(t.stop_loss)}</td>
    `;
    body.appendChild(tr);
  });
}

function renderModeCompare() {
  const sp = STATE.ranking.sprint?.tickers?.slice(0, 10) ?? [];
  const ma = STATE.ranking.marathon?.tickers?.slice(0, 10) ?? [];
  const spSet = new Set(sp.map(t => t.ticker));
  const maSet = new Set(ma.map(t => t.ticker));
  const overlap = sp.filter(t => maSet.has(t.ticker));

  const renderList = (list, otherSet, elId) => {
    const el = document.getElementById(elId);
    el.innerHTML = "";
    list.forEach(t => {
      const li = document.createElement("li");
      li.textContent = `${t.ticker} ${t.name || ""}`;
      if (otherSet.has(t.ticker)) li.classList.add("shared");
      el.appendChild(li);
    });
  };
  renderList(sp, maSet, "cmp-sprint");
  renderList(ma, spSet, "cmp-marathon");
  document.getElementById("cmp-overlap").textContent =
    `${overlap.length} / 10 (${(overlap.length * 10).toFixed(0)}%)`;
}

function renderNewLeaders() {
  const body = document.getElementById("new-leaders-body");
  body.innerHTML = "";
  const items = STATE.newLeaders?.new_leaders ?? [];
  items.slice(0, 12).forEach(t => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${t.ticker}</td><td>${t.name || ""}</td><td>${t.sector || ""}</td>
      <td>${fmt.num(t.rank_velocity_5d, 0)}</td>
      <td>${fmt.num(t.acceleration, 0)}</td>
      <td>${t.tier_change}</td>
    `;
    body.appendChild(tr);
  });
}

function renderSectors() {
  const body = document.getElementById("sector-body");
  body.innerHTML = "";
  const items = STATE.sectors?.sectors ?? [];
  items.slice(0, 10).forEach(s => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${s.sector}</td><td>${s.n_tickers}</td><td>${s.n_top_tier}</td>
      <td>${fmt.num(s.avg_mode_score, 1)}</td>
      <td>${fmt.pctFromUnit(s.total_weight)}</td>
    `;
    body.appendChild(tr);
  });
}

function renderRiskAlerts() {
  const body = document.getElementById("risk-body");
  const items = STATE.riskAlerts?.alerts ?? [];
  if (items.length === 0) {
    body.className = "risk-empty";
    body.textContent = "현재 트리거된 손절 없음.";
    return;
  }
  body.className = "";
  body.innerHTML = items.map(a => `
    <div class="risk-item">
      <span class="ticker">${a.ticker}</span>
      <span>${a.entry_mode}</span>
      <span>진입 ${fmt.price(a.entry_price)} → 현재 ${fmt.price(a.current_price)}</span>
      <span class="triggered">${a.triggered.join(", ")}</span>
    </div>
  `).join("");
}

function renderAll() {
  renderRegime();
  renderLeaderboard();
  renderModeCompare();
  renderNewLeaders();
  renderSectors();
  renderRiskAlerts();
}

function setupHandlers() {
  document.querySelectorAll(".mode-toggle button").forEach(btn => {
    btn.addEventListener("click", () => {
      STATE.mode = btn.dataset.mode;
      document.querySelectorAll(".mode-toggle button").forEach(b => b.classList.toggle("active", b === btn));
      renderRegime();
      renderLeaderboard();
    });
  });
  document.getElementById("filter-tier").addEventListener("change", e => {
    STATE.filters.tier = e.target.value; renderLeaderboard();
  });
  document.getElementById("filter-sector").addEventListener("change", e => {
    STATE.filters.sector = e.target.value; renderLeaderboard();
  });
  document.getElementById("filter-market").addEventListener("change", e => {
    STATE.filters.market = e.target.value; renderLeaderboard();
  });
}

(async () => {
  setupHandlers();
  await loadAll();
  renderAll();
})();
