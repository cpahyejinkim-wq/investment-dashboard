// Mode Toggle: Sprint <-> Marathon. Soft Migration is enforced on the backend
// (positions.json), so the toggle merely switches which mode's view is shown.

function initModeToggle(state, onChange) {
  const buttons = document.querySelectorAll(".toggle-btn");
  buttons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const mode = btn.dataset.mode;
      if (mode === state.mode) return;
      console.info("[Mode Toggle] Soft Migration: 기존 포지션은 진입 시 모드 룰을 유지합니다.");
      buttons.forEach((b) => b.classList.toggle("active", b === btn));
      state.mode = mode;
      onChange();
    });
  });
}

function initialActiveMode(state, mode) {
  if (state.__initialized) return;
  state.__initialized = true;
  state.mode = mode;
  document.querySelectorAll(".toggle-btn").forEach((b) => {
    b.classList.toggle("active", b.dataset.mode === mode);
  });
}
