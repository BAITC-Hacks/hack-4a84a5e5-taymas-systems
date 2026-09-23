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

// Редактор карточки: балл и его разбивку считает сервер, здесь только их показ.
(() => {
  const form = document.getElementById("card-form");
  if (!form) return;
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

  // Досчёт балла от прежнего к новому; без JS сразу виден итог.
  const num = document.querySelector(".gauge-num .score-big");
  if (num && !reduce && num.dataset.from !== num.dataset.to) {
    const from = +num.dataset.from, to = +num.dataset.to, t0 = performance.now() + 200, dur = 1600;
    const tick = t => {
      const k = Math.max(0, Math.min(1, (t - t0) / dur)), e = 1 - Math.pow(1 - k, 3);
      num.textContent = Math.round(from + (to - from) * e);
      if (k < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }

  // Наклейки и задания ведут к полю
  const go = name => {
    const input = form.querySelector(`[name="${name}"]`);
    if (!input) return;
    const field = input.closest(".field");
    field.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "center" });
    field.classList.remove("flash"); void field.offsetWidth; field.classList.add("flash");
    setTimeout(() => input.focus({ preventScroll: true }), reduce ? 0 : 450);
  };
  document.querySelectorAll("[data-go]").forEach(b => b.addEventListener("click", () => go(b.dataset.go)));

  // Наклон наклеек за курсором
  if (!reduce) document.querySelectorAll(".sticker").forEach(s => {
    s.addEventListener("pointermove", e => {
      const r = s.getBoundingClientRect(), x = (e.clientX - r.left) / r.width - .5, y = (e.clientY - r.top) / r.height - .5;
      s.style.transform = `rotateY(${x * 18}deg) rotateX(${-y * 18}deg) translateZ(8px)`;
    });
    s.addEventListener("pointerleave", () => { s.style.transform = ""; });
  });

  // Метка «изменено» — визуальная; балл пересчитает сервер после сохранения
  form.querySelectorAll(".field input, .field textarea").forEach(el => {
    const initial = el.value;
    el.addEventListener("input", () => el.closest(".field").classList.toggle("dirty", el.value !== initial));
  });

  // Подсветка за курсором и глаза маскота
  const card = document.getElementById("gauge-card");
  const eyes = document.querySelectorAll(".mascot .eye");
  if (!reduce) addEventListener("pointermove", e => {
    if (card) {
      const r = card.getBoundingClientRect();
      card.style.setProperty("--mx", `${e.clientX - r.left}px`);
      card.style.setProperty("--my", `${e.clientY - r.top}px`);
    }
    eyes.forEach(eye => {
      const r = eye.ownerSVGElement.getBoundingClientRect(), cx = r.left + r.width / 2, cy = r.top + r.height / 2;
      const a = Math.atan2(e.clientY - cy, e.clientX - cx), d = Math.min(3.5, Math.hypot(e.clientX - cx, e.clientY - cy) / 60);
      eye.setAttribute("transform", `translate(${Math.cos(a) * d} ${Math.sin(a) * d})`);
    });
  });

  // Подтверждение: магнитная кнопка, подсказка без галочки, конфетти перед отправкой
  const toggle = document.getElementById("confirm-toggle"), btn = document.getElementById("publish-btn"), msg = document.getElementById("confirm-msg");
  if (!toggle || !btn) return;
  if (!reduce) {
    btn.addEventListener("pointermove", e => {
      const r = btn.getBoundingClientRect();
      btn.style.transform = `translate(${(e.clientX - r.left - r.width / 2) * .06}px, ${(e.clientY - r.top - r.height / 2) * .25}px)`;
    });
    btn.addEventListener("pointerleave", () => { btn.style.transform = ""; });
  }
  toggle.addEventListener("change", () => { msg.textContent = ""; });
  const burst = (x, y) => {
    const colors = ["var(--accent)", "var(--pop)", "var(--pop-2)", "var(--good)", "var(--warn)"];
    for (let i = 0; i < 70; i++) {
      const c = document.createElement("i"), a = Math.random() * Math.PI * 2, d = 120 + Math.random() * 320;
      c.className = "confetti";
      c.style.cssText = `left:${x}px;top:${y}px;background:${colors[i % colors.length]};--dx:${Math.cos(a) * d}px;--dy:${Math.sin(a) * d - 80 + Math.random() * 260}px;--r:${Math.random() * 720 - 360}deg;--t:${900 + Math.random() * 700}ms`;
      document.body.appendChild(c);
      setTimeout(() => c.remove(), 1700);
    }
  };
  let sending = false;
  btn.addEventListener("click", e => {
    if (sending) return;
    if (!toggle.checked) {
      e.preventDefault();
      msg.textContent = "Сначала включите «Подтверждаю, что карточка составлена верно» — без подтверждения баллы не начисляются.";
      const sw = toggle.closest(".switch");
      sw.classList.remove("shake"); void sw.offsetWidth; sw.classList.add("shake");
      return;
    }
    if (reduce) return;
    e.preventDefault();
    sending = true;
    burst(e.clientX || innerWidth / 2, e.clientY || innerHeight / 2);
    setTimeout(() => form.requestSubmit ? form.requestSubmit(btn) : btn.click(), 650);
  });
})();
