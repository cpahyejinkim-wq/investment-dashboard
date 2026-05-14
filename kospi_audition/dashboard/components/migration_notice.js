function renderMigrationNotice(state) {
  const el = document.getElementById("migration-banner");
  if (!el) return;
  const positions = state.data.positions;
  if (!positions || !positions.positions || positions.positions.length === 0) {
    el.classList.add("hidden");
    return;
  }
  const mismatched = positions.positions.filter((p) => p.entry_mode && p.entry_mode !== state.mode);
  if (mismatched.length === 0) {
    el.classList.add("hidden");
    return;
  }
  el.classList.remove("hidden");
  el.textContent =
    `Soft Migration: ${mismatched.length}개 포지션이 진입 시 모드(`
    + Array.from(new Set(mismatched.map((p) => p.entry_mode))).join(", ")
    + `) 룰을 그대로 유지합니다.`;
}
