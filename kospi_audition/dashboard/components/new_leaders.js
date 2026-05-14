function renderNewLeaders(state) {
  const tbody = document.querySelector("#new-leaders tbody");
  tbody.innerHTML = "";
  const leaders = state.data.leaders;
  if (!leaders || !leaders.new_leaders) return;
  leaders.new_leaders.forEach((l) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${l.ticker}</td>
      <td class="tier-${l.tier}">${l.tier || "-"}</td>
      <td>${l.rank_velocity_5d ?? "-"}</td>
      <td>${l.rank_past ?? "-"} → ${l.rank_today ?? "-"}</td>
      <td>${l.acceleration_pct ? Number(l.acceleration_pct).toFixed(1) : "-"}</td>
    `;
    tbody.appendChild(tr);
  });
}
