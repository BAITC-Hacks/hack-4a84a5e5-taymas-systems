// Черновик из фото (HAC-58). Здесь только доставка файла на сервер и вставка текста в поле:
// что на фото — описывает модель на сервере, что оставить в черновике — решает человек.
(() => {
  const box = document.querySelector(".photo-attach");
  const textarea = document.querySelector('textarea[name="text"]');
  if (!box || !textarea) return;
  const input = box.querySelector('input[type="file"]');
  const status = box.querySelector(".photo-status");
  const preview = box.querySelector(".photo-preview");
  const img = preview.querySelector("img");
  const caption = preview.querySelector("figcaption");
  const dropZone = textarea.closest(".draft-box") || textarea;
  const MAX = 5 * 1024 * 1024;
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  let busy = false;

  const say = (text, kind) => {
    status.textContent = text;
    status.className = "photo-status" + (kind ? " " + kind : "");
    status.hidden = !text;
  };

  const insert = draft => {
    const current = textarea.value.trim();
    textarea.value = current ? current + "\n\n" + draft : draft;
    textarea.dispatchEvent(new Event("input", { bubbles: true })); // счётчик символов в app.js
    textarea.focus();
    textarea.scrollIntoView({ block: "center", behavior: reduce ? "auto" : "smooth" });
  };

  const industry = () => {
    const r = document.querySelector('input[name="industry"]:checked');
    return r ? r.value : "";
  };

  const send = async file => {
    if (busy || !file) return;
    if (!/^image\/(jpeg|png|webp|gif)$/.test(file.type)) return say("Подходят JPEG, PNG, WebP и GIF.", "err");
    if (file.size > MAX) return say("Фото больше 5 МБ. Уменьшите снимок или сделайте скриншот.", "err");
    busy = true;
    box.classList.add("busy");
    say("Смотрю на фото…", "busy");
    if (preview.dataset.url) URL.revokeObjectURL(preview.dataset.url);
    const url = URL.createObjectURL(file);
    preview.dataset.url = url;
    img.src = url;
    caption.textContent = file.name || "снимок";
    preview.hidden = false;
    const body = new FormData();
    body.append("photo", file, file.name || "photo");
    body.append("industry", industry());
    try {
      const res = await fetch(box.dataset.endpoint, { method: "POST", body });
      let data = null;
      try { data = await res.json(); } catch (e) {}
      if (!data) return say("Сервер ответил не по формату (" + res.status + "). Опишите задачу словами.", "err");
      if (data.ok && data.draft) {
        insert(data.draft);
        const unclear = data.description && data.description.unclear;
        caption.textContent = unclear ? "По фото не определить: " + unclear : "Описано только то, что видно";
        say(data.message || "Описание вставлено в черновик — проверьте и поправьте.", "ok");
      } else {
        say(data.message || "Не удалось разобрать фото. Опишите задачу словами.", "err");
      }
    } catch (e) {
      say("Нет связи с сервером. Опишите задачу словами.", "err");
    } finally {
      busy = false;
      box.classList.remove("busy");
      input.value = "";
    }
  };

  input.addEventListener("change", () => send(input.files && input.files[0]));

  // Ctrl+V со скриншотом прямо в поле черновика.
  textarea.addEventListener("paste", e => {
    const items = (e.clipboardData && e.clipboardData.items) || [];
    const item = [...items].find(i => i.kind === "file" && i.type.startsWith("image/"));
    if (!item) return;
    e.preventDefault();
    send(item.getAsFile());
  });

  // Перетаскивание файла на поле черновика.
  ["dragenter", "dragover"].forEach(t => dropZone.addEventListener(t, e => {
    if ([...e.dataTransfer.types].includes("Files")) { e.preventDefault(); dropZone.classList.add("dragover"); }
  }));
  ["dragleave", "drop"].forEach(t => dropZone.addEventListener(t, () => dropZone.classList.remove("dragover")));
  dropZone.addEventListener("drop", e => {
    const f = e.dataTransfer.files && e.dataTransfer.files[0];
    if (f) { e.preventDefault(); send(f); }
  });
})();
