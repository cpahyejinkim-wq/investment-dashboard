// Mode Toggle (Stage 1: sprint active, marathon visible but disabled until Stage 2).

function initModeToggle(state, onChange) {
  const buttons = document.querySelectorAll(".toggle-btn");
  buttons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const mode = btn.dataset.mode;
      if (mode === state.mode) return;
      // Soft Migration toast guidance (Stage 1 displays only).
      console.info("[Mode Toggle] 기존 포지션은 진입 시 모드 룰을 유지합니다 (Soft Migration).");
      buttons.forEach((b) => b.classList.toggle("active", b === btn));
      state.mode = mode;
      onChange();
    });
  });
}
