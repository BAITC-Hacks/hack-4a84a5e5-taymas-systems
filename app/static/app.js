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

  // Мягкая подсветка карточки балла за курсором
  const card = document.getElementById("gauge-card");
  if (card && !reduce) card.addEventListener("pointermove", e => {
      const r = card.getBoundingClientRect();
      card.style.setProperty("--mx", `${e.clientX - r.left}px`);
      card.style.setProperty("--my", `${e.clientY - r.top}px`);
  });

  // Подтверждение: магнитная кнопка и подсказка, если не включён переключатель
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
  btn.addEventListener("click", e => {
    if (!toggle.checked) {
      e.preventDefault();
      msg.textContent = "Сначала включите «Подтверждаю, что карточка составлена верно» — без подтверждения баллы не начисляются.";
      const sw = toggle.closest(".switch");
      sw.classList.remove("shake"); void sw.offsetWidth; sw.classList.add("shake");
      return;
    }
  });
})();

// Выпадающие списки в стиле сайта поверх обычного <select>.
// Сам <select> остаётся в форме и отправляет значение; без JS работает как раньше.
(() => {
  let open = null;
  const close = (dd, focusBtn) => {
    if (!dd) return;
    dd.list.hidden = true;
    dd.btn.setAttribute("aria-expanded", "false");
    dd.box.classList.remove("open");
    if (focusBtn) dd.btn.focus();
    if (open === dd) open = null;
  };

  document.querySelectorAll("select:not([multiple])").forEach((select, n) => {
    const box = document.createElement("div");
    box.className = "dd";
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "dd-btn" + (select.classList.contains("invalid") ? " invalid" : "");
    btn.setAttribute("aria-haspopup", "listbox");
    btn.setAttribute("aria-expanded", "false");
    const list = document.createElement("ul");
    list.className = "dd-list";
    list.id = `dd-list-${n}`;
    list.setAttribute("role", "listbox");
    list.hidden = true;
    btn.setAttribute("aria-controls", list.id);

    const items = [...select.options].map((opt, i) => {
      const li = document.createElement("li");
      li.setAttribute("role", "option");
      li.tabIndex = -1;
      li.textContent = opt.textContent.trim();
      li.dataset.index = i;
      list.appendChild(li);
      return li;
    });

    const dd = { box, btn, list };
    const sync = () => {
      const opt = select.options[select.selectedIndex];
      btn.textContent = opt ? opt.textContent.trim() : "";
      btn.classList.toggle("placeholder", !!opt && opt.value === "");
      items.forEach((li, i) => li.setAttribute("aria-selected", String(i === select.selectedIndex)));
    };
    const choose = i => {
      if (select.selectedIndex !== i) {
        select.selectedIndex = i;
        select.dispatchEvent(new Event("change", { bubbles: true }));
      }
      sync();
      close(dd, true);
    };
    const openList = () => {
      if (open && open !== dd) close(open);
      list.hidden = false;
      box.classList.add("open");
      btn.setAttribute("aria-expanded", "true");
      open = dd;
      (items[select.selectedIndex] || items[0])?.focus();
    };

    btn.addEventListener("click", () => (list.hidden ? openList() : close(dd, true)));
    btn.addEventListener("keydown", e => {
      if (["ArrowDown", "ArrowUp", "Enter", " "].includes(e.key)) { e.preventDefault(); openList(); }
    });
    // preventDefault: список лежит внутри <label>, иначе клик по пункту снова «нажмёт» кнопку.
    list.addEventListener("click", e => { e.preventDefault(); const li = e.target.closest("li"); if (li) choose(+li.dataset.index); });
    list.addEventListener("keydown", e => {
      const i = items.indexOf(document.activeElement);
      const move = j => items[Math.max(0, Math.min(items.length - 1, j))].focus();
      if (e.key === "ArrowDown") { e.preventDefault(); move(i + 1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); move(i - 1); }
      else if (e.key === "Home") { e.preventDefault(); move(0); }
      else if (e.key === "End") { e.preventDefault(); move(items.length - 1); }
      else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); if (i >= 0) choose(i); }
      else if (e.key === "Escape") { e.preventDefault(); close(dd, true); }
      else if (e.key === "Tab") close(dd);
    });

    select.classList.add("dd-native");
    select.tabIndex = -1;
    select.setAttribute("aria-hidden", "true");
    select.parentNode.insertBefore(box, select);
    box.append(btn, list, select);
    select.addEventListener("change", sync);
    sync();
  });

  document.addEventListener("click", e => { if (open && !open.box.contains(e.target)) close(open); });
})();

// ИИ-агент в интерфейсе: показ того, что агент делает. Сами вопросы, карточку и рейтинг готовит сервер.
(() => {
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

  // Сетка в шапке главной подсвечивается за курсором
  const hero = document.querySelector(".home-hero");
  if (hero && !reduce) hero.addEventListener("pointermove", e => {
    const r = hero.getBoundingClientRect();
    hero.style.setProperty("--hx", `${e.clientX - r.left}px`);
    hero.style.setProperty("--hy", `${e.clientY - r.top}px`);
  });

  // Консоль с примером запуска: строки печатаются по очереди, потом цикл повторяется
  const log = document.querySelector(".console-log");
  if (log && !reduce) {
    const lines = [...log.children], texts = lines.map(li => li.textContent);
    const run = async () => {
      const wait = ms => new Promise(r => setTimeout(r, ms));
      for (;;) {
        lines.forEach(li => { li.classList.add("later"); li.textContent = ""; });
        for (let i = 0; i < lines.length; i++) {
          const li = lines[i];
          li.classList.remove("later"); li.classList.add("typing");
          for (let k = 1; k <= texts[i].length; k += 2) { li.textContent = texts[i].slice(0, k); await wait(18); }
          li.textContent = texts[i]; li.classList.remove("typing");
          await wait(li.classList.contains("c-ask") ? 500 : 350);
        }
        await wait(5000);
      }
    };
    run();
  }

  // Пока сервер обрабатывает форму (с ИИ это несколько секунд), показываем шаги агента
  document.querySelectorAll("form[data-agent]").forEach(form => {
    form.addEventListener("submit", e => {
      if (e.defaultPrevented) return;
      const steps = form.dataset.agent.split("|");
      const box = document.createElement("div");
      box.className = "agent-overlay";
      box.setAttribute("role", "status");
      box.innerHTML = `<div class="agent-panel"><div class="agent-orb"></div><h3>ИИ-агент работает</h3><ol class="agent-steps">${steps.map(s => `<li>${s}</li>`).join("")}</ol><p class="agent-note">Обычно это занимает несколько секунд.</p></div>`;
      document.body.appendChild(box);
      const items = box.querySelectorAll("li");
      let i = 0;
      const next = () => {
        items.forEach((li, j) => { li.className = j < i ? "done" : j === i ? "now" : ""; });
        if (i < items.length - 1) { i++; setTimeout(next, 1100); }
      };
      next();
    });
  });
  // Возврат кнопкой «Назад» не должен оставлять экран ожидания
  addEventListener("pageshow", () => document.querySelectorAll(".agent-overlay").forEach(o => o.remove()));

  // Вопросы появляются по одному, будто агент их печатает
  const cards = [...document.querySelectorAll(".q-form .q-card")];
  if (cards.length && !reduce) {
    const typing = document.createElement("div");
    typing.className = "q-typing";
    typing.innerHTML = "<i></i><i></i><i></i> агент формулирует вопросы";
    cards[0].before(typing);
    cards.forEach(c => { c.hidden = true; });
    cards.forEach((c, n) => setTimeout(() => {
      c.hidden = false;
      if (n === cards.length - 1) typing.remove(); else c.after(typing);
    }, 500 + n * 450));
  }

  // Карточка поднялась на новый уровень — короткое поздравление
  const gauge = document.getElementById("gauge-card");
  if (gauge && gauge.dataset.levelup) {
    const toast = document.createElement("div");
    toast.className = "levelup";
    toast.setAttribute("role", "status");
    toast.innerHTML = `<b>▲</b><span><small>новый уровень</small>«${gauge.dataset.levelup}»</span>`;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 5000);
    if (!reduce) {
      const r = gauge.getBoundingClientRect(), cx = r.left + r.width / 2, cy = r.top + r.height / 3;
      const colors = ["var(--accent)", "var(--good)", "var(--pop)", "var(--pop-2)"];
      for (let n = 0; n < 36; n++) {
        const s = document.createElement("i");
        s.className = "spark";
        const a = Math.random() * Math.PI * 2, d = 80 + Math.random() * 140;
        s.style.cssText = `left:${cx}px;top:${cy}px;background:${colors[n % 4]};--dx:${Math.cos(a) * d}px;--dy:${Math.sin(a) * d + 60}px;--r:${Math.random() * 540}deg`;
        document.body.appendChild(s);
        setTimeout(() => s.remove(), 1200);
      }
    }
  }
})();
