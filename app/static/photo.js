// HAC-58: сначала цель и фото, затем проверяемое предложение, затем явный перенос.
(() => {
  'use strict';
  const box = document.querySelector('.photo-attach');
  const textarea = document.querySelector('textarea[name="text"]');
  if (!box || !textarea) return;
  const input = box.querySelector('input[type="file"]'), status = box.querySelector('.photo-status');
  const preview = box.querySelector('.photo-preview'), img = preview.querySelector('img');
  const analyze = box.querySelector('.photo-analyze'), processing = box.querySelector('.photo-processing');
  const result = box.querySelector('.photo-result'), candidate = box.querySelector('.photo-draft');
  const apply = box.querySelector('.photo-apply'), ready = box.querySelector('.photo-ready-note');
  const dropZone = textarea.closest('.draft-box') || textarea;
  let file = null, busy = false, objectURL = '', source = '', timer;
  const say = (text, kind = '') => { status.textContent = text; status.className = `photo-status ${kind}`; status.hidden = !text; };
  const updateReady = () => {
    const length = textarea.value.trim().length;
    analyze.disabled = busy || !file || length < 10 || length > 4000;
    ready.textContent = !file ? 'Добавьте фото ситуации к вашему описанию.' : length < 10 ? 'Напишите выше хотя бы одну фразу: что хотите улучшить или решить.' : length > 4000 ? 'Сократите описание до 4000 символов.' : 'Готово: ваша цель + фото. Нажмите, чтобы предложить постановку задачи.';
  };
  const choose = selected => {
    if (!selected || busy) return;
    if (!/^image\/(jpeg|png|webp|gif)$/.test(selected.type)) return say('Подходят JPEG, PNG, WebP и GIF.', 'err');
    if (!selected.size || selected.size > 5 * 1024 * 1024) return say('Нужен непустой снимок размером до 5 МБ.', 'err');
    file = selected; result.hidden = true; say('');
    if (objectURL) URL.revokeObjectURL(objectURL);
    objectURL = URL.createObjectURL(file); img.src = objectURL;
    preview.querySelector('figcaption').textContent = `${file.name || 'Снимок'} · ${Math.ceil(file.size / 1024)} КБ`;
    preview.hidden = false; updateReady();
  };
  input.addEventListener('change', () => { choose(input.files?.[0]); input.value = ''; });
  textarea.addEventListener('input', updateReady);
  textarea.addEventListener('paste', event => {
    const item = [...(event.clipboardData?.items || [])].find(i => i.kind === 'file' && i.type.startsWith('image/'));
    if (item) { event.preventDefault(); choose(item.getAsFile()); }
  });
  ['dragenter','dragover'].forEach(type => dropZone.addEventListener(type, event => {
    if ([...event.dataTransfer.types].includes('Files')) { event.preventDefault(); dropZone.classList.add('dragover'); }
  }));
  ['dragleave','drop'].forEach(type => dropZone.addEventListener(type, () => dropZone.classList.remove('dragover')));
  dropZone.addEventListener('drop', event => { const item = event.dataTransfer.files?.[0]; if (item) { event.preventDefault(); choose(item); } });
  analyze.addEventListener('click', async () => {
    updateReady(); if (analyze.disabled) return;
    source = textarea.value.trim(); busy = true; updateReady(); input.disabled = true;
    box.classList.add('busy'); processing.hidden = false; result.hidden = true; apply.disabled = false; say('');
    const started = Date.now();
    const tick = () => { box.querySelector('.photo-clock').textContent = `${Math.floor((Date.now() - started) / 1000)} с`; };
    tick(); timer = setInterval(tick, 1000);
    box.querySelector('.photo-context-line').textContent = `Контекст: ${source.length} символов · фото: ${Math.ceil(file.size / 1024)} КБ`;
    const body = new FormData(); body.append('photo', file, file.name || 'photo'); body.append('context', source);
    body.append('industry', document.querySelector('input[name="industry"]:checked')?.value || '');
    try {
      const response = await fetch(box.dataset.endpoint, {method:'POST', body, signal:AbortSignal.timeout(180000)});
      const data = await response.json();
      if (data.description) {
        const description = data.description;
        result.querySelector('.photo-source').textContent = source;
        result.querySelector('.photo-seen').textContent = description.seen || 'Фото не добавило подтверждённых деталей.';
        result.querySelector('.photo-proposal').textContent = description.proposal || 'Проверьте предложенную постановку по вашему запросу.';
        candidate.value = data.draft || '';
        const list = result.querySelector('ul'); list.replaceChildren();
        for (const question of description.questions || []) { const li = document.createElement('li'); li.textContent = question; list.append(li); }
        result.querySelector('.photo-unclear').textContent = description.unclear || '';
        apply.hidden = !data.ok || !data.draft; result.hidden = false;
      }
      say(data.message || 'Проверьте предложенный черновик.', data.ok ? 'ok' : 'err');
    } catch (error) {
      say(error.name === 'TimeoutError' ? 'AI отвечает дольше обычного. Попробуйте ещё раз; ваш текст сохранён в поле.' : 'Не удалось получить ответ. Попробуйте ещё раз или продолжите словами.', 'err');
    } finally {
      clearInterval(timer); busy = false; input.disabled = false; box.classList.remove('busy'); processing.hidden = true; updateReady();
    }
  });
  apply.addEventListener('click', () => {
    if (textarea.value.trim() !== source) { say('Вы уже изменили исходный текст. Повторите анализ с новой формулировкой или скопируйте нужный фрагмент вручную.', 'err'); return; }
    if (!candidate.value.trim() || candidate.value.length > 4000) { say('Черновик должен содержать от 1 до 4000 символов.', 'err'); return; }
    textarea.value = candidate.value.trim(); textarea.dispatchEvent(new Event('input', {bubbles:true}));
    apply.disabled = true; say('Черновик перенесён. Проверьте текст и получите уточняющие вопросы.', 'ok');
    textarea.focus(); textarea.scrollIntoView({block:'center', behavior:matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'});
  });
  textarea.closest('form')?.addEventListener('submit', event => { if (busy) { event.preventDefault(); say('Дождитесь предложения AI по фото, затем продолжите.', 'err'); } }, true);
  updateReady();
})();
