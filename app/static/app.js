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

(() => {
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

  // Наклон карточек за курсором
  if (!reduce) document.querySelectorAll(".tilt").forEach(el => {
    el.addEventListener("pointermove", e => {
      const r = el.getBoundingClientRect(), x = (e.clientX - r.left) / r.width - .5, y = (e.clientY - r.top) / r.height - .5;
      el.style.transform = `rotateY(${x * 10}deg) rotateX(${-y * 10}deg) translateY(-4px)`;
    });
    el.addEventListener("pointerleave", () => { el.style.transform = ""; });
  });

  // Живой счётчик символов черновика
  document.querySelectorAll(".counter-live").forEach(c => {
    const field = document.querySelector(`[name="${c.dataset.for}"]`);
    if (!field) return;
    const limit = +field.dataset.limit || 0;
    const upd = () => { c.textContent = field.value.length; c.style.color = limit && field.value.length > limit ? "var(--bad)" : ""; };
    field.addEventListener("input", upd);
    upd();
  });

  // Сколько вопросов уже отвечено
  const answered = document.querySelector(".answered-live b");
  if (answered) {
    const areas = document.querySelectorAll(".q-form textarea");
    const upd = () => { answered.textContent = [...areas].filter(a => a.value.trim()).length; };
    areas.forEach(a => a.addEventListener("input", upd));
    upd();
  }
})();
