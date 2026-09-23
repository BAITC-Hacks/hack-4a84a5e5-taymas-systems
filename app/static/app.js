// Поведение интерфейса. Только оформление: данные и рейтинг считает сервер.
(() => {
  const root = document.documentElement;

  // Цветотип: выбор запоминается в браузере; без localStorage просто не запоминается.
  const swatches = document.querySelectorAll(".swatch[data-p]");
  const mark = p => swatches.forEach(s => s.setAttribute("aria-pressed", String(s.dataset.p === p)));
  mark(root.dataset.palette || "night");
  swatches.forEach(s => s.addEventListener("click", () => {
    root.dataset.palette = s.dataset.p;
    mark(s.dataset.p);
    try { localStorage.setItem("aisana-palette", s.dataset.p); } catch (e) {}
  }));
})();
