"use strict";

// ============================================================
// KAP Dashboard — front-end (light professional theme)
// ============================================================

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
  num:  (v, d = 1) => (v == null || Number.isNaN(Number(v))) ? "—" : Number(v).toFixed(d),
  pct:  (v, d = 1) => (v == null || Number.isNaN(Number(v))) ? "—" : Number(v).toFixed(d) + "%",
  // raw decimal (e.g. 0.082) → "+8.2%"
  pctSigned: (v, d = 1) => {
    if (v == null || Number.isNaN(Number(v))) return "—";
    const n = Number(v) * 100;
    return (n >= 0 ? "+" : "") + n.toFixed(d) + "%";
  },
  pctFromUnit: (v, d = 1) => (v == null) ? "—" : (Number(v) * 100).toFixed(d) + "%",
  int:   (v) => v == null ? "—" : Math.round(Number(v)).toLocaleString(),
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

// ----------------------------------------------------------------
// Rendering
// ----------------------------------------------------------------
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
    hint.textContent = `현재 모드(${STATE.mode})가 Regime 권장 모드입니다.`;
  } else if (r.recommended_mode === "cash") {
    hint.textContent = "⚠ Risk-Off — 모든 신규 진입이 차단됩니다.";
  } else {
    hint.textContent = `⚠ Regime은 ${r.recommended_mode} 모드를 권장합니다.`;
  }

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

function tierBadge(tier) {
  return `<span class="tier-badge ${tier}">${tier}</span>`;
}

function scoreCell(scorePct, tier) {
  const v = (scorePct == null || Number.isNaN(Number(scorePct))) ? 0 : Number(scorePct);
  const cls = (tier || "").toLowerCase();
  return `<div class="score-cell ${cls}">
    <span class="num">${v.toFixed(1)}</span>
    <span class="mini-bar"><span style="width:${Math.min(100, Math.max(0, v))}%"></span></span>
  </div>`;
}

function tickerCell(t) {
  const name = (t.name && t.name.length) ? t.name : "(이름 없음)";
  const market = t.market || "";
  return `<div class="ticker-cell">
    <span class="name" title="${name}">${name}<span class="market-tag ${market}">${market}</span></span>
    <span class="code">${t.ticker}</span>
  </div>`;
}

function rsCell(v) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  const cls = Number(v) >= 0 ? "val-up" : "val-down";
  return `<span class="${cls}">${fmt.pctSigned(v)}</span>`;
}

function renderLeaderboard() {
  const r = STATE.ranking[STATE.mode];
  const body = document.getElementById("leaderboard-body");
  document.getElementById("lb-mode").textContent = STATE.mode.charAt(0).toUpperCase() + STATE.mode.slice(1);
  document.getElementById("kpi-current-mode").textContent = STATE.mode.charAt(0).toUpperCase() + STATE.mode.slice(1);
  document.getElementById("universe-size").textContent = r?.universe_size ?? "—";
  body.innerHTML = "";
  if (!r) {
    body.innerHTML = `<tr><td colspan="12" style="text-align:center;padding:24px;color:var(--text-muted)">데이터 로딩 실패. <code>output/ranking_${STATE.mode}.json</code> 확인.</td></tr>`;
    return;
  }

  const tickers = applyFilters(r.tickers);
  const top = tickers.slice(0, 40);

  // Pyramid + KPI counts (from full universe, not filtered view)
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

  // Sector dropdown (populate once)
  const sectorSel = document.getElementById("filter-sector");
  if (sectorSel.options.length <= 1) {
    const sectors = [...new Set(r.tickers.map(t => t.sector).filter(Boolean))].sort();
    sectors.forEach(s => {
      const o = document.createElement("option"); o.value = s; o.textContent = s;
      sectorSel.appendChild(o);
    });
  }

  // Rows
  if (top.length === 0) {
    body.innerHTML = `<tr><td colspan="12" style="text-align:center;padding:24px;color:var(--text-muted)">필터 조건에 맞는 종목이 없습니다.</td></tr>`;
    return;
  }
  top.forEach((t, i) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${i + 1}</td>
      <td>${tickerCell(t)}</td>
      <td>${t.sector || "—"}</td>
      <td>${tierBadge(t.tier)}</td>
      <td>${scoreCell(t.mode_score_pct, t.tier)}</td>
      <td>${fmt.num(t.leader_score, 1)}</td>
      <td>${fmt.num(t.rank_velocity_pct, 0)}</td>
      <td>${fmt.num(t.acceleration, 0)}</td>
      <td>${rsCell(t.rs_20d)}</td>
      <td>${rsCell(t.rs_60d)}</td>
      <td>${fmt.pctFromUnit(t.weight, 2)}</td>
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
      const name = t.name || t.ticker;
      li.textContent = `${name} (${t.ticker})`;
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
  if (items.length === 0) {
    body.innerHTML = `<tr><td colspan="5" style="text-align:center;padding:14px;color:var(--text-muted)">신규 리더 후보 없음</td></tr>`;
    return;
  }
  items.slice(0, 12).forEach(t => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${tickerCell(t)}</td>
      <td>${t.sector || "—"}</td>
      <td>${fmt.num(t.rank_velocity_5d, 0)}</td>
      <td>${fmt.num(t.acceleration, 0)}</td>
      <td>${t.tier_change || "—"}</td>
    `;
    body.appendChild(tr);
  });
}

function renderSectors() {
  const body = document.getElementById("sector-body");
  body.innerHTML = "";
  const items = STATE.sectors?.sectors ?? [];
  if (items.length === 0) {
    body.innerHTML = `<tr><td colspan="5" style="text-align:center;padding:14px;color:var(--text-muted)">데이터 없음</td></tr>`;
    return;
  }
  items.slice(0, 10).forEach(s => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><strong>${s.sector}</strong></td>
      <td>${s.n_tickers}</td>
      <td>${s.n_top_tier}</td>
      <td>${fmt.num(s.avg_mode_score, 1)}</td>
      <td>${fmt.pctFromUnit(s.total_weight, 2)}</td>
    `;
    body.appendChild(tr);
  });
}

function renderRiskAlerts() {
  const body = document.getElementById("risk-body");
  const items = STATE.riskAlerts?.alerts ?? [];
  if (items.length === 0) {
    body.className = "risk-empty";
    body.textContent = "✓ 현재 트리거된 손절 없음";
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

// ----------------------------------------------------------------
// Tooltip system (for the ⓘ icons in column headers)
// ----------------------------------------------------------------
function setupTooltips() {
  const tip = document.getElementById("tooltip");
  document.body.addEventListener("mouseover", (e) => {
    const el = e.target.closest(".info");
    if (!el) return;
    const text = el.dataset.tip || "";
    if (!text) return;
    tip.textContent = text;
    tip.classList.remove("hidden");
    const r = el.getBoundingClientRect();
    // position below the icon
    let left = r.left;
    let top = r.bottom + 6;
    // keep inside viewport
    const tipW = Math.min(280, window.innerWidth - 16);
    if (left + tipW > window.innerWidth - 8) left = window.innerWidth - tipW - 8;
    tip.style.left = left + "px";
    tip.style.top = top + "px";
    tip.style.maxWidth = tipW + "px";
  });
  document.body.addEventListener("mouseout", (e) => {
    if (e.target.closest(".info")) tip.classList.add("hidden");
  });
}

// ----------------------------------------------------------------
// Event handlers
// ----------------------------------------------------------------
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

  // Help panel toggle
  const help = document.getElementById("help-panel");
  document.getElementById("btn-help-leaderboard").addEventListener("click", () => {
    help.classList.toggle("hidden");
  });
  document.getElementById("help-close").addEventListener("click", () => {
    help.classList.add("hidden");
  });
}

// ----------------------------------------------------------------
// Boot
// ----------------------------------------------------------------
(async () => {
  setupHandlers();
  setupTooltips();
  await loadAll();
  renderAll();
})();
