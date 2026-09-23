// HAC-57: прогрессивное улучшение; сервер остаётся источником порядка и баллов.
(() => {
  'use strict';
  const css = document.createElement('link');
  css.rel = 'stylesheet'; css.href = '/static/live.css'; document.head.append(css);
  const reduce = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
  const el = (tag, text, cls) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (cls) node.className = cls;
    return node;
  };
  const getJSON = async url => {
    const response = await fetch(url, {cache: 'no-store', signal: AbortSignal.timeout(10000)});
    if (!response.ok) throw new Error('network');
    return response.json();
  };
  let toastTimer;
  const toast = text => {
    let node = document.querySelector('.live-toast');
    if (!node) { node = el('div', '', 'live-toast'); node.setAttribute('role', 'status'); document.body.append(node); }
    node.textContent = text;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => node.remove(), 5000);
  };
  // Следующий опрос начинается после завершения предыдущего; скрытые вкладки не опрашиваются.
  const poll = (fn, delay) => {
    const run = async () => {
      if (!document.hidden) { try { await fn(); } catch (_) { /* Следующий опрос восстановит связь. */ } }
      setTimeout(run, delay);
    };
    run();
  };
  const idOf = row => row.querySelector('a.task-title')?.getAttribute('href')?.split('/').pop();
  if (location.pathname === '/catalog') {
    const status = el('p', 'Живой каталог · проверяем обновления…', 'live-state');
    document.querySelector('.counter')?.after(status);
    let previous = null;
    poll(async () => {
      try {
        const data = await getJSON(`/catalog.json${location.search}`);
        const signature = JSON.stringify(data.cards);
        if (signature === previous) { status.textContent = 'Живой каталог · обновляется автоматически'; return; }
        const response = await fetch(location.href, {cache: 'no-store', signal: AbortSignal.timeout(10000)});
        if (!response.ok) throw new Error('network');
        const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
        let list = document.querySelector('.task-list');
        const fresh = doc.querySelector('.task-list');
        const oldRows = new Map([...document.querySelectorAll('.task-list .task-row')].map(r => [idOf(r), r]));
        const before = new Map([...oldRows].map(([id, row]) => [id, {top: row.getBoundingClientRect().top, rank: Number(row.querySelector('.rank')?.textContent)}]));
        let movement = '', added = false;
        if (fresh) {
          if (!list) { list = el('ol', undefined, 'task-list'); (document.querySelector('.empty') || status).after(list); document.querySelector('.empty')?.remove(); }
          const nodes = [];
          for (const freshRow of fresh.querySelectorAll('.task-row')) {
            const id = idOf(freshRow), row = oldRows.get(id) || freshRow;
            const item = data.cards.find(c => c.id === id);
            if (row !== freshRow) { row.innerHTML = freshRow.innerHTML; row.className = freshRow.className; }
            if (item) row.querySelector('.rank').textContent = item.position;
            nodes.push(row);
            const prior = before.get(id);
            if (!prior) added = true;
            else if (item && prior.rank > item.position) movement = `«${item.title}» поднялась с ${prior.rank}-го места на ${item.position}-е`;
          }
          list.replaceChildren(...nodes);
          for (const row of nodes) {
            const prior = before.get(idOf(row));
            if (!prior) continue;
            const delta = prior.top - row.getBoundingClientRect().top;
            if (delta && !reduce()) row.animate([{transform: `translateY(${delta}px)`}, {transform: 'translateY(0)'}], {duration: 650, easing: 'cubic-bezier(.2,.8,.2,1)'});
            if (prior.rank > Number(row.querySelector('.rank')?.textContent)) row.classList.add('live-risen');
          }
        } else {
          list?.remove();
          if (!document.querySelector('.empty') && doc.querySelector('.empty')) status.after(doc.querySelector('.empty'));
        }
        const counter = document.querySelector('.counter');
        if (counter && doc.querySelector('.counter')) counter.textContent = doc.querySelector('.counter').textContent;
        // Рекомендации выбранной команды тоже зависят от опубликованных карточек.
        const recommendations = document.querySelector('.recommendations');
        if (recommendations && doc.querySelector('.recommendations')) recommendations.replaceWith(doc.querySelector('.recommendations'));
        if (previous !== null && (added || movement)) toast(added ? 'Новая задача в каталоге' : movement);
        previous = signature;
        status.textContent = 'Живой каталог · обновляется автоматически';
      } catch (error) { status.textContent = 'Обновление временно недоступно · показана последняя версия'; throw error; }
    }, 2500);
  }
  const feed = document.getElementById('live-feed');
  if (feed) {
    let previous;
    poll(async () => {
      const data = await getJSON('/feed.json'), signature = JSON.stringify(data.events);
      if (signature === previous) return;
      const list = el('ol');
      for (const event of data.events) {
        const row = el('li'), date = new Date(event.at);
        const time = el('time', date.toLocaleString('ru-RU', {day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit'}));
        time.dateTime = event.at;
        const link = el('a', event.text); link.href = `/tasks/${encodeURIComponent(event.card_id)}`;
        row.append(time, link); list.append(row);
      }
      feed.replaceChildren(el('h2', 'Сейчас в Challenge Hub'), data.events.length ? list : el('p', 'Первые публикации и отклики появятся здесь.'));
      previous = signature;
    }, 5000);
  }
  const editor = location.pathname.match(/^\/business\/cards\/([^/]+)\/edit$/);
  if (editor) {
    const scoreNode = document.querySelector('.score-big');
    const from = Number(scoreNode?.dataset.from ?? document.querySelector('.score-change .old')?.textContent);
    const to = Number(scoreNode?.dataset.to ?? scoreNode?.textContent);
    const level = s => s >= 90 ? 3 : s >= 70 ? 2 : s >= 40 ? 1 : 0;
    const labels = ['Черновик', 'Рабочая', 'Готовая', 'Приоритетная'];
    if (Number.isFinite(from) && Number.isFinite(to) && level(to) > level(from)) {
      const banner = el('p', `Уровень повышен: ${labels[level(from)]} → ${labels[level(to)]}`, 'live-level-up');
      banner.setAttribute('role', 'status');
      (document.querySelector('.editor') || scoreNode).before(banner);
      if (!reduce()) for (let i = 0; i < 16; i++) {
        const p = el('i', undefined, 'live-particle'); p.setAttribute('aria-hidden', 'true');
        p.style.setProperty('--dx', `${Math.cos(i * Math.PI / 8) * 200}px`);
        p.style.setProperty('--dy', `${Math.sin(i * Math.PI / 8) * 90}px`);
        banner.append(p); setTimeout(() => p.remove(), 1000);
      }
    }
    if (scoreNode && Number.isFinite(to)) {
      const position = el('p', '', 'live-position');
      (document.querySelector('.gauge-foot') || scoreNode.parentElement).after(position);
      poll(async () => {
        const data = await getJSON('/catalog.json'), own = data.cards.find(c => c.id === editor[1]);
        // Для существующей карточки дата публикации при подтверждении НЕ меняется.
        const ahead = data.cards.filter(c => c.id !== editor[1] && (c.score > to || (c.score === to && own && (c.published_at || '') > (own.published_at || ''))));
        const next = ahead.length + 1, total = data.total + (own ? 0 : 1);
        position.textContent = `${own ? `Сейчас ${own.position} из ${data.total} → ` : ''}После подтверждения: ${next} из ${total}. По сохранённым полям.`;
      }, 5000);
    }
  }
})();
