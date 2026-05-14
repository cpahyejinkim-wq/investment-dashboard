function renderRisk(state) {
  const ul = document.getElementById("risk-alerts");
  ul.innerHTML = "";
  const risk = state.data.risk;
  if (!risk || !risk.alerts || risk.alerts.length === 0) {
    ul.innerHTML = `<li style="border-left-color:#2a8;background:rgba(40,170,90,0.07)">알림 없음</li>`;
    return;
  }
  risk.alerts.forEach((a) => {
    const li = document.createElement("li");
    li.textContent = `${a.ticker} · ${a.type} · price ${a.price} ≤ stop ${a.stop_loss} (${a.mode})`;
    ul.appendChild(li);
  });
}
