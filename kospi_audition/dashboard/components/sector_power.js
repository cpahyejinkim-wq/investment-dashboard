function renderSectorPower(state) {
  const tbody = document.querySelector("#sector-power tbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  const data = state.data.sector_power;
  if (!data || !data.sectors) return;
  data.sectors.slice(0, 5).forEach((s) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${s.sector ?? "-"}</td>
      <td>${s.sector_power != null ? Number(s.sector_power).toFixed(1) : "-"}</td>
      <td>${s.sector_rs_pct != null ? Number(s.sector_rs_pct).toFixed(1) : "-"}</td>
      <td>${s.new_leader_count ?? 0}</td>
      <td>${s.trading_amount_growth != null ? Number(s.trading_amount_growth).toFixed(2) : "-"}</td>
    `;
    tbody.appendChild(tr);
  });
}
