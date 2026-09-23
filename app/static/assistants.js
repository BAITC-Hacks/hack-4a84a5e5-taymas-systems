(() => {
  'use strict';
  const layout = document.querySelector('.assistant-layout');
  if (!layout) return;
  const el = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
  const json = async (url, body) => {
    const response = await fetch(url, {method: body ? 'POST' : 'GET', headers: body ? {'Content-Type':'application/json'} : {}, body: body ? JSON.stringify(body) : undefined, signal: AbortSignal.timeout(180000)});
    if (!response.ok) throw new Error('Запрос не выполнен. Проверьте ввод и попробуйте снова.');
    return response.json();
  };
  const form = document.getElementById('assistant-form');
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const button = form.querySelector('[type="submit"]'), status = document.getElementById('assistant-status');
    if (button.disabled) return;
    const query = form.elements.message.value;
    button.disabled = true; status.textContent = 'Читаю карточки и проверяю ответ…';
    try {
      const response = await fetch(form.action, {method:'POST', body:new FormData(form), signal:AbortSignal.timeout(180000)});
      if (!response.ok) throw new Error('Не удалось получить ответ. Попробуйте ещё раз.');
      const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
      const results = doc.getElementById('assistant-results');
      if (!results) throw new Error('Ответ не распознан. Обновите страницу.');
      document.getElementById('assistant-results').replaceWith(results);
      const history = doc.querySelector('[name="history"]');
      if (history) form.elements.history.value = history.value;
      if (!results.querySelector('.notice.error')) {
        const conversation = document.getElementById('assistant-conversation');
        conversation.append(el('p', query || 'Помоги улучшить карточку'));
        while (conversation.children.length > 5) conversation.firstElementChild.remove();
        form.elements.message.value = '';
      }
      status.textContent = 'Готово. Можно уточнить запрос.';
    } catch (error) { status.textContent = error.name === 'TimeoutError' ? 'Ответ занимает слишком много времени. Попробуйте снова.' : error.message; }
    finally { button.disabled = false; }
  });
  document.addEventListener('click', async event => {
    const chip = event.target.closest('[data-query]');
    if (chip) { form.elements.message.value = chip.dataset.query; form.elements.message.focus(); }
    const planButton = event.target.closest('[data-plan]');
    if (planButton) {
      const target = document.getElementById('assistant-plan');
      planButton.disabled = true; target.replaceChildren(el('p', 'Готовлю план старта…'));
      try {
        const data = await json(`/assistants/tasks/${encodeURIComponent(planButton.dataset.plan)}/plan.json`);
        target.replaceChildren(el('h2', 'План старта'), el('h3', data.card.title), el('p', 'План-шаблон · на основе полей карточки', 'muted'));
        const list = el('ol');
        for (const step of data.steps) {
          const item = el('li'); item.append(el('b', step.title), el('p', step.action), el('p', step.evidence ? `Из карточки: ${step.evidence}` : 'В карточке не указано — уточните у бизнеса.', 'muted')); list.append(item);
        }
        const draftForm = el('form', undefined, 'form-stack');
        const label = el('label', 'Ваша идея — напишите свой подход');
        const idea = el('textarea'); idea.required = true; idea.maxLength = 2000;
        idea.placeholder = 'Что вы предлагаете и как это решит задачу бизнеса?'; label.append(idea);
        const planLabel = el('label', 'План — уточните предложенные шаги');
        const plan = el('textarea'); plan.required = true; plan.maxLength = 2000;
        plan.value = 'Уточнить задачу с бизнесом → проверить доступ к данным → собрать минимальный прототип → провести проверку и демо.'; planLabel.append(plan);
        const review = el('button', 'Проверить отклик с AI-наставником'); review.type = 'submit';
        const reviewResult = el('div'); reviewResult.setAttribute('role', 'status');
        draftForm.append(label, planLabel, review, reviewResult);
        draftForm.addEventListener('submit', async e => {
          e.preventDefault(); review.disabled = true; reviewResult.replaceChildren(el('p', 'Сверяю ваш черновик с карточкой…'));
          try {
            const result = await json(`/assistants/tasks/${encodeURIComponent(data.card.id)}/review.json`, {idea:idea.value, plan:plan.value});
            reviewResult.replaceChildren(el('p', result.mode === 'stub' ? result.mode_note : `AI-наставник · ${result.mode}`, 'muted'));
            for (const check of result.checks) reviewResult.append(el('p', `${check.done ? '✓' : '○'} ${check.label}`));
            const questions = el('ul'); result.questions.forEach(q => questions.append(el('li', q)));
            reviewResult.append(el('b', 'Вопросы перед отправкой'), questions, el('p', result.notice, 'muted'));
          } catch (error) { reviewResult.replaceChildren(el('p', error.message)); }
          finally { review.disabled = false; }
        });
        const copy = el('button', 'Скопировать черновик'); copy.type = 'button';
        copy.addEventListener('click', async () => {
          try { await navigator.clipboard.writeText(`Идея: ${idea.value}\n\nПлан: ${plan.value}`); copy.textContent = 'Скопировано'; }
          catch (_) { idea.focus(); idea.select(); copy.textContent = 'Скопируйте текст из полей вручную'; }
        });
        const transfer = el('button', 'Перенести в форму отклика →'); transfer.type = 'button';
        transfer.addEventListener('click', () => {
          if (!draftForm.reportValidity()) return;
          try { sessionStorage.setItem(`aisana-proposal-${data.card.id}`, JSON.stringify({idea:idea.value, plan:plan.value})); location.href = `${data.card.url}#proposals`; }
          catch (_) { reviewResult.append(el('p', 'Хранилище браузера недоступно. Скопируйте черновик вручную.')); }
        });
        target.append(list, draftForm, copy, transfer, el('p', data.notice, 'muted'));
      } catch (error) { target.replaceChildren(el('p', error.message)); }
      finally { planButton.disabled = false; }
    }
    const fieldButton = event.target.closest('[data-preview-field]');
    if (fieldButton && previewForm) { previewForm.elements.field.value = fieldButton.dataset.previewField; loadField(); previewForm.scrollIntoView({block:'center', behavior:matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'}); previewForm.elements.value.focus(); }
  });
  document.getElementById('assistant-compare')?.addEventListener('click', async () => {
    const ids = [...document.querySelectorAll('[data-compare]:checked')].map(c => c.dataset.compare);
    const target = document.getElementById('assistant-comparison');
    if (!ids.length || ids.length > 3) { target.replaceChildren(el('p', 'Выберите от одной до трёх задач.')); return; }
    target.replaceChildren(el('p', 'Сравниваю факты карточек…'));
    try {
      const params = new URLSearchParams(); ids.forEach(id => params.append('ids', id));
      const data = await json(`/assistants/compare.json?${params}`);
      target.replaceChildren(el('p', data.notice, 'muted'));
      for (const card of data.cards) {
        const item = el('article'), link = el('a', card.title); link.href = card.url;
        const title = el('h3'); title.append(link); item.append(title, el('p', `${card.score}/100 · ${card.level_label}`));
        const list = el('dl');
        for (const [key, label] of [['data','Данные'],['constraints','Ограничения'],['expected_result','Результат'],['success_criteria','Критерии успеха']]) list.append(el('dt', label), el('dd', card[key] || 'Не указано — уточните у бизнеса'));
        item.append(list); target.append(item);
      }
    } catch (error) { target.replaceChildren(el('p', error.message)); }
  });
  const previewForm = document.getElementById('assistant-preview-form');
  const initial = previewForm ? JSON.parse(document.getElementById('assistant-card-fields').textContent) : {};
  const patches = {};
  const transfer = document.getElementById('assistant-transfer');
  const loadField = () => { const key = previewForm.elements.field.value; previewForm.elements.value.value = patches[key] ?? initial[key] ?? ''; };
  if (previewForm) {
    previewForm.elements.field.addEventListener('change', loadField);
    loadField();
    previewForm.addEventListener('submit', async event => {
      event.preventDefault();
      const target = document.getElementById('assistant-preview-result');
      const button = previewForm.querySelector('[type="submit"]');
      const candidate = {...patches, [previewForm.elements.field.value]:previewForm.elements.value.value};
      transfer.hidden = true; button.disabled = true;
      try {
        const data = await json(`/business/cards/${encodeURIComponent(layout.dataset.cardId)}/preview.json`, {fields:candidate});
        Object.assign(patches, candidate);
        target.replaceChildren(el('p', `${data.before} → ${data.after} (${data.delta >= 0 ? '+' : ''}${data.delta})`, 'assistant-preview-total'), el('p', `${data.level_label} · позиция после подтверждения: ${data.position.position} из ${data.position.total}`));
        const changes = el('ul'); Object.keys(patches).forEach(key => { const option = [...previewForm.elements.field.options].find(o => o.value === key); changes.append(el('li', option?.textContent || key)); });
        target.append(el('p', 'В предпросмотре изменены:'), changes, el('p', data.notice, 'muted'));
        transfer.hidden = false;
      } catch (error) { target.replaceChildren(el('p', error.message)); }
      finally { button.disabled = false; }
    });
    // Переносится только проверенный набор, а не новые неоценённые правки в textarea.
    transfer.addEventListener('click', () => {
      try {
        sessionStorage.setItem(`aisana-coach-${layout.dataset.cardId}`, JSON.stringify({fields:patches, original:initial}));
        location.href = `/business/cards/${encodeURIComponent(layout.dataset.cardId)}/edit`;
      } catch (_) { document.getElementById('assistant-preview-result').append(el('p', 'Хранилище браузера недоступно. Скопируйте проверенный текст в редактор вручную.')); }
    });
  }
})();
