'use strict';
/* Интерфейс «Сборщика баз». Один файл без сборки: экраны рисуются функциями view*. */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const main = $('#main');
const TOKEN = { 'X-App-Token': $('meta[name=app-token]').content };

const S = {
  view: 'collect', meta: null, settings: null, templates: [],
  collect: { city: '', niche: '', queries: [], districts: [], useDistricts: false, pickedDistricts: [], sources: ['twogis', 'yandex_maps'], enrich: true, findSites: true },
  job: null, logs: [], lastLog: 0, wasBusy: false, notified: '',
  base: { q: '', status: '', segment: '', city: '', tag: '', flags: {}, sort: 'id', dir: 'desc', page: 0, mode: localStorage.getItem('baseMode') || 'table' },
  exp: { format: 'xlsx', fields: null, useFilters: true },
};
const PAGE = 50;
const FLAGS = [['has_tg', 'Есть Telegram'], ['has_wa', 'Есть WhatsApp'], ['only_phone', 'Только телефон'], ['no_site', 'Нет сайта'],
  ['site_down', 'Сайт не работает'], ['no_booking', 'Нет онлайн-записи'], ['many_reviews', 'Много отзывов'], ['hide_nmc', 'Скрыть «не мой клиент»']];

async function api(path, body, method) {
  const opts = { method: method || (body === undefined ? 'GET' : 'POST') };
  opts.headers = { ...TOKEN };
  if (body !== undefined) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
  let res;
  try { res = await fetch(path, opts); } catch (e) { throw new Error('Нет связи с приложением. Перезапустите программу.'); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || data.detail || `Ошибка ${res.status}`);
  return data;
}
function toast(text, kind) {
  const el = document.createElement('div');
  el.className = 'toast' + (kind === 'error' ? ' error' : '');
  el.textContent = text;
  $('#toasts').append(el);
  setTimeout(() => el.remove(), kind === 'error' ? 7000 : 3500);
}
const guard = (fn) => async (...args) => { try { return await fn(...args); } catch (e) { toast(e.message, 'error'); } };
const openLink = guard((url) => api('/api/open', { url }));
const openFolder = guard((path) => api('/api/open', { path }));
async function copyText(text) {
  try { await navigator.clipboard.writeText(text); } catch (e) {
    const ta = document.createElement('textarea'); ta.value = text; document.body.append(ta); ta.select(); document.execCommand('copy'); ta.remove();
  }
}
const phoneFmt = (p) => (p && p.length === 11 ? `+${p[0]} ${p.slice(1, 4)} ${p.slice(4, 7)}-${p.slice(7, 9)}-${p.slice(9)}` : p);
const statusTitle = (key) => (S.meta.statuses.find((s) => s.key === key) || {}).title || key;
const dateFmt = (s) => (s ? s.slice(8, 10) + '.' + s.slice(5, 7) + '.' + s.slice(0, 4) + (s.length > 10 ? ' ' + s.slice(11, 16) : '') : '');
const plural = (n, a, b, c) => { const m = n % 100, d = n % 10; return m > 10 && m < 20 ? c : d === 1 ? a : d > 1 && d < 5 ? b : c; };

/* ---------- навигация ---------- */
const VIEWS = {};
function go(view) {
  S.view = view;
  $$('#nav button').forEach((b) => b.classList.toggle('on', b.dataset.view === view));
  main.scrollTop = 0;
  VIEWS[view]();
}
$('#nav').addEventListener('click', (e) => { const b = e.target.closest('button'); if (b) go(b.dataset.view); });
document.addEventListener('click', (e) => {
  const link = e.target.closest('[data-open]');
  if (link) { e.preventDefault(); e.stopPropagation(); openLink(link.dataset.open); }
});

/* ---------- новый сбор ---------- */
VIEWS.collect = function () {
  const c = S.collect;
  main.innerHTML = `<div class="view">
    <div class="head"><div><h1>Новый сбор</h1><p>Укажите город и нишу. Варианты запроса подберутся сами, лишние можно убрать.</p></div></div>
    <div class="grid2">
      <div class="card stack" id="form">
        <div class="row" style="align-items:flex-end">
          <label class="f grow">Город<input type="text" id="city" list="cities" placeholder="Казань" value="${esc(c.city)}"></label>
          <label class="f grow">Ниша<input type="text" id="niche" placeholder="натяжные потолки" value="${esc(c.niche)}"></label>
          <button class="btn" id="expand">Подобрать варианты</button>
        </div>
        <datalist id="cities">${S.meta.cities.map((n) => `<option value="${esc(n)}">`).join('')}</datalist>
        <div>
          <div class="row between" style="margin-bottom:8px"><span class="muted small">Запросы, по которым пойдёт поиск</span><span class="muted small" id="q-count"></span></div>
          <div class="chips" id="queries"></div>
          <div class="row" style="margin-top:9px"><input type="text" id="add-q" placeholder="Добавить свой запрос и нажать Enter"><button class="btn sm" id="add-q-btn">Добавить</button></div>
        </div>
        <div>
          <label class="check"><input type="checkbox" id="use-d" ${c.useDistricts ? 'checked' : ''}>Перебирать по районам города</label>
          <div id="districts-box" style="margin-top:9px" ${c.useDistricts ? '' : 'hidden'}>
            <div class="chips" id="districts"></div>
            <div class="row" style="margin-top:9px"><input type="text" id="add-d" placeholder="Добавить район"><button class="btn sm" id="add-d-btn">Добавить</button></div>
          </div>
        </div>
        <div>
          <div class="muted small" style="margin-bottom:8px">Источники</div>
          <div class="sources">${S.meta.sources.map((s) => `<label class="source check"><input type="checkbox" data-source="${s.key}" ${c.sources.includes(s.key) ? 'checked' : ''}>${esc(s.title)}</label>`).join('')}</div>
        </div>
        <div class="stack" style="gap:8px">
          <label class="check"><input type="checkbox" id="enrich" ${c.enrich ? 'checked' : ''}>Проверять сайты компаний и собирать с них контакты</label>
          <label class="check"><input type="checkbox" id="find-sites" ${c.findSites ? 'checked' : ''}>Если сайта нет в карточке, искать его в поиске Яндекса</label>
        </div>
        <div class="row between">
          <span class="muted small" id="plan"></span>
          <button class="btn primary big" id="start">Начать сбор</button>
        </div>
      </div>
      <div class="stack">
        <div id="resume-box"></div>
        <div class="card" id="progress"></div>
        <div class="card"><h2>Журнал</h2><div class="log" id="log"></div></div>
      </div>
    </div></div>`;
  const sync = () => { c.city = $('#city').value.trim(); c.niche = $('#niche').value.trim(); };
  const drawQueries = () => {
    $('#queries').innerHTML = c.queries.length
      ? c.queries.map((q, i) => `<span class="chip">${esc(q)}<button data-rm-q="${i}" title="Убрать">×</button></span>`).join('')
      : '<span class="muted small">Пока пусто. Введите нишу и нажмите «Подобрать варианты».</span>';
    drawPlan();
  };
  const drawDistricts = () => {
    $('#districts').innerHTML = c.districts.length
      ? c.districts.map((d) => `<span class="chip toggle ${c.pickedDistricts.includes(d) ? 'on' : ''}" data-d="${esc(d)}" tabindex="0">${esc(d)}</span>`).join('')
      : '<span class="muted small">Для этого города районы не заданы — добавьте вручную.</span>';
    drawPlan();
  };
  const drawPlan = () => {
    const d = c.useDistricts ? Math.max(1, c.pickedDistricts.length) : 1;
    const n = c.queries.length * d * c.sources.length;
    $('#q-count').textContent = c.queries.length ? `${c.queries.length} ${plural(c.queries.length, 'запрос', 'запроса', 'запросов')}` : '';
    $('#plan').textContent = n ? `Будет ${n} ${plural(n, 'поиск', 'поиска', 'поисков')}: запросы × районы × источники` : '';
  };
  const expand = guard(async () => {
    sync();
    if (!c.niche) return toast('Сначала введите нишу.', 'error');
    const r = await api('/api/variants', { niche: c.niche, city: c.city });
    c.queries = [...new Set([...r.queries, ...c.queries])];
    c.districts = r.districts; c.pickedDistricts = [...r.districts];
    drawQueries(); drawDistricts();
  });
  const addTo = (input, list, redraw, also) => {
    const v = $(input).value.trim();
    if (v && !list.includes(v)) { list.push(v); if (also) also.push(v); }
    $(input).value = ''; redraw();
  };
  $('#expand').onclick = expand;
  $('#niche').onkeydown = (e) => { if (e.key === 'Enter') expand(); };
  $('#add-q-btn').onclick = () => addTo('#add-q', c.queries, drawQueries);
  $('#add-q').onkeydown = (e) => { if (e.key === 'Enter') addTo('#add-q', c.queries, drawQueries); };
  $('#add-d-btn').onclick = () => addTo('#add-d', c.districts, drawDistricts, c.pickedDistricts);
  $('#add-d').onkeydown = (e) => { if (e.key === 'Enter') addTo('#add-d', c.districts, drawDistricts, c.pickedDistricts); };
  $('#queries').onclick = (e) => { const i = e.target.dataset.rmQ; if (i !== undefined) { c.queries.splice(+i, 1); drawQueries(); } };
  $('#districts').onclick = (e) => {
    const d = e.target.dataset.d; if (!d) return;
    c.pickedDistricts = c.pickedDistricts.includes(d) ? c.pickedDistricts.filter((x) => x !== d) : [...c.pickedDistricts, d];
    drawDistricts();
  };
  $('#use-d').onchange = (e) => { c.useDistricts = e.target.checked; $('#districts-box').hidden = !c.useDistricts; drawPlan(); };
  $('#enrich').onchange = (e) => { c.enrich = e.target.checked; };
  $('#find-sites').onchange = (e) => { c.findSites = e.target.checked; };
  $$('[data-source]').forEach((el) => { el.onchange = () => { c.sources = $$('[data-source]:checked').map((x) => x.dataset.source); drawPlan(); }; });
  $('#start').onclick = guard(async () => {
    sync();
    if (!c.city) return toast('Укажите город.', 'error');
    if (!c.queries.length && c.niche) c.queries = [c.niche];
    if (!c.queries.length) return toast('Добавьте хотя бы один запрос.', 'error');
    if (!c.sources.length) return toast('Выберите хотя бы один источник.', 'error');
    await api('/api/job/start', { city: c.city, niche: c.niche || c.queries[0], queries: c.queries,
      districts: c.useDistricts ? c.pickedDistricts : [], sources: c.sources, enrich: c.enrich, find_sites: c.findSites });
    S.logs = []; toast('Сбор начат. Откроется окно браузера — не закрывайте его.');
    poll();
  });
  drawQueries(); drawDistricts(); drawJob(true);
};

const STATE_TITLES = { idle: 'Сбор не идёт', running: 'Идёт сбор', paused: 'На паузе', captcha: 'Нужна ваша помощь', stopping: 'Останавливаюсь…' };
function drawJob(full) {
  const st = S.job; if (!st || S.view !== 'collect' || !$('#progress')) return;
  const j = st.job, busy = st.status !== 'idle';
  $('#start').disabled = busy;
  $('#resume-box').innerHTML = st.resumable ? `<div class="alert"><div class="grow"><b>Есть незавершённый сбор №${j.id}</b><br><span class="small">${esc(j.params.city)}, ${esc(j.params.niche)}: обработано карточек ${j.cards_done} из ${j.cards_total}. Продолжится с того же места.</span></div><button class="btn primary" id="resume-job">Продолжить сбор</button></div>` : '';
  if ($('#resume-job')) $('#resume-job').onclick = guard(async () => { await api('/api/job/resume_job', { job_id: j.id }); poll(); });
  const title = !busy && j && j.status === 'done' ? `Сбор №${j.id} завершён` : STATE_TITLES[st.status];
  $('#progress').innerHTML = `
    <div class="row between"><span class="state"><span class="dot ${st.status}"></span>${title}</span>
      <span class="row">
        ${st.status === 'running' ? '<button class="btn sm" data-act="pause">Пауза</button>' : ''}
        ${st.status === 'paused' || st.status === 'captcha' ? '<button class="btn sm primary" data-act="resume">Продолжить</button>' : ''}
        ${busy ? `<button class="btn sm danger" data-act="stop" ${st.status === 'stopping' ? 'disabled' : ''}>Стоп</button>` : ''}
      </span></div>
    ${st.status === 'captcha' ? `<div class="alert" style="margin-top:12px"><div><b>${esc(st.message)}</b><br><span class="small">Программа ничего не делает, пока вы не нажмёте «Продолжить».</span></div></div>` : ''}
    ${st.status !== 'captcha' && st.message ? `<p class="muted small" style="margin-top:8px">${esc(st.message)}</p>` : ''}
    <div class="bar"><div style="width:${j ? j.percent : 0}%"></div></div>
    <div class="row between small muted" style="margin-bottom:12px"><span>${esc(st.current || (j ? `${j.params.city}, ${j.params.niche}` : 'Заполните форму слева и нажмите «Начать сбор»'))}</span><span>${j ? j.percent + '%' : ''}</span></div>
    <div class="nums">
      <div class="num"><b>${j ? `${j.tasks_done}/${j.tasks_total}` : '0'}</b><span>поисков пройдено</span></div>
      <div class="num"><b>${j ? `${j.cards_done}/${j.cards_total}` : '0'}</b><span>карточек открыто</span></div>
      <div class="num"><b>${j ? j.added : 0}</b><span>новых компаний</span></div>
      <div class="num"><b>${st.per_hour}</b><span>страниц за час</span></div>
    </div>`;
  $$('#progress [data-act]').forEach((b) => { b.onclick = guard(async () => { await api('/api/job/' + b.dataset.act, {}); poll(); }); });
  const log = $('#log');
  if (full) log.dataset.n = '';
  if (log.dataset.n !== String(S.lastLog)) {
    const stick = log.scrollTop + log.clientHeight >= log.scrollHeight - 30;
    log.innerHTML = S.logs.length ? S.logs.map((l) => `<div class="${l.level}"><time>${l.time}</time><span>${esc(l.text)}</span></div>`).join('')
      : '<div class="muted">Здесь появятся события сбора.</div>';
    log.dataset.n = String(S.lastLog);
    if (stick || full) log.scrollTop = log.scrollHeight;
  }
}
let pollTimer = null;
async function poll() {
  clearTimeout(pollTimer);
  try {
    const st = await fetch('/api/job/status?since=' + S.lastLog, { headers: TOKEN }).then((r) => r.json());
    S.job = st;
    if (st.logs.length) { S.logs = S.logs.concat(st.logs).slice(-500); S.lastLog = st.logs[st.logs.length - 1].id; }
    const busy = st.status !== 'idle';
    const mark = $('#nav-job');
    mark.className = st.status === 'running' ? 'live' : busy ? 'wait' : '';
    if (st.status === 'captcha' && S.notified !== st.message) { S.notified = st.message; toast(st.message, 'error'); document.title = '⚠ Нужна капча — Сборщик баз'; }
    if (st.status !== 'captcha') { S.notified = ''; document.title = 'Сборщик баз'; }
    if (S.wasBusy && !busy) { refreshCounters(); if (S.view === 'base') VIEWS.base(); }
    S.wasBusy = busy;
    drawJob(false);
    pollTimer = setTimeout(poll, busy ? 1000 : 4000);
  } catch (e) { pollTimer = setTimeout(poll, 4000); }
}
async function refreshCounters() {
  try {
    const [f, t] = await Promise.all([api('/api/facets'), api('/api/today')]);
    S.facets = f;
    $('#nav-total').textContent = f.total || '';
    const n = t.planned.length + t.read_silent.length + t.no_reply.length;
    $('#nav-today').textContent = n || ''; $('#nav-today').className = n ? 'hot' : '';
  } catch (e) { /* счётчики не критичны */ }
}

/* ---------- база ---------- */
function baseFilters() {
  const b = S.base, f = { ...b.flags };
  for (const k of ['q', 'status', 'segment', 'city', 'tag']) if (b[k]) f[k] = b[k];
  return f;
}
function contactIcons(c) {
  return `${c.phones.length ? `<span class="ic" title="${esc(c.phones.map(phoneFmt).join(', '))}">тел</span>` : ''}${c.telegram ? '<span class="ic tg">TG</span>' : ''}${c.whatsapp ? '<span class="ic wa">WA</span>' : ''}${c.max ? '<span class="ic tg">MAX</span>' : ''}${c.vk ? '<span class="ic">VK</span>' : ''}${c.emails.length ? '<span class="ic">@</span>' : ''}${c.site ? `<span class="ic ${c.site_status === 'down' ? 'bad' : 'web'}" title="${esc(c.site)}">сайт</span>` : ''}${c.booking ? '<span class="ic wa" title="Онлайн-запись">запись</span>' : ''}`;
}
VIEWS.base = async function () {
  const b = S.base;
  if (!$('#base-view')) {
    await refreshCounters();
    const f = S.facets || { cities: [], segments: [] };
    main.innerHTML = `<div class="view" id="base-view">
      <div class="head"><div><h1>База</h1><p id="base-count"></p></div>
        <div class="seg" id="mode"><button data-mode="table">Таблица</button><button data-mode="cards">Карточки</button></div></div>
      <div class="toolbar">
        <input type="search" id="bq" placeholder="Поиск: название, телефон, адрес, сайт" value="${esc(b.q)}">
        <select id="b-status"><option value="">Любой статус</option>${S.meta.statuses.map((s) => `<option value="${s.key}">${esc(s.title)}</option>`).join('')}</select>
        <select id="b-segment"><option value="">Любой сегмент</option>${f.segments.map((s) => `<option value="${esc(s.name)}">${esc(s.name)} (${s.n})</option>`).join('')}</select>
        <select id="b-city"><option value="">Все города</option>${f.cities.map((n) => `<option>${esc(n)}</option>`).join('')}</select>
      </div>
      <div class="chips" style="margin-bottom:14px">${FLAGS.map(([k, t]) => `<span class="chip toggle ${b.flags[k] ? 'on' : ''}" data-flag="${k}" tabindex="0">${t}</span>`).join('')}</div>
      <div class="card table-card" id="base-body"></div></div>`;
    $('#b-status').value = b.status; $('#b-segment').value = b.segment; $('#b-city').value = b.city;
    let timer;
    $('#bq').oninput = (e) => { clearTimeout(timer); timer = setTimeout(() => { b.q = e.target.value.trim(); b.page = 0; loadBase(); }, 250); };
    for (const [id, key] of [['#b-status', 'status'], ['#b-segment', 'segment'], ['#b-city', 'city']]) $(id).onchange = (e) => { b[key] = e.target.value; b.page = 0; loadBase(); };
    $$('[data-flag]').forEach((el) => { el.onclick = () => { const k = el.dataset.flag; if (b.flags[k]) delete b.flags[k]; else b.flags[k] = 1; el.classList.toggle('on'); b.page = 0; loadBase(); }; });
    $('#mode').onclick = (e) => { const m = e.target.dataset.mode; if (m) { b.mode = m; localStorage.setItem('baseMode', m); loadBase(); } };
  }
  loadBase();
};
const loadBase = guard(async () => {
  const b = S.base;
  const params = new URLSearchParams({ ...baseFilters(), sort: b.sort, dir: b.dir, limit: PAGE, offset: b.page * PAGE });
  const data = await api('/api/companies?' + params);
  if (!$('#base-body')) return;
  $$('#mode button').forEach((x) => x.classList.toggle('on', x.dataset.mode === b.mode));
  $('#base-count').textContent = `${data.total} ${plural(data.total, 'компания', 'компании', 'компаний')}` + (Object.keys(baseFilters()).length ? ' по фильтру' : '');
  const body = $('#base-body');
  if (!data.items.length) {
    body.innerHTML = Object.keys(baseFilters()).length
      ? '<div class="empty"><b>Ничего не нашлось</b>Снимите часть фильтров или измените запрос.</div>'
      : '<div class="empty"><b>База пока пустая</b>Запустите первый сбор — компании появятся здесь.<br><br><button class="btn primary" id="to-collect">Перейти к сбору</button></div>';
    if ($('#to-collect')) $('#to-collect').onclick = () => go('collect');
    return;
  }
  const cols = [['name', 'Компания'], ['', 'Контакты'], ['district', 'Район'], ['reviews', 'Отзывы'], ['segment', 'Чем интересна'], ['status', 'Статус']];
  const pager = `<div class="pager"><span>${b.page * PAGE + 1}–${b.page * PAGE + data.items.length} из ${data.total}</span><span class="row">
    <button class="btn sm" id="prev" ${b.page ? '' : 'disabled'}>Назад</button><button class="btn sm" id="next" ${(b.page + 1) * PAGE < data.total ? '' : 'disabled'}>Дальше</button></span></div>`;
  if (b.mode === 'cards') {
    body.innerHTML = `<div class="cards">${data.items.map((c) => `<div class="ccard" data-id="${c.id}" style="${c.not_my_client ? 'opacity:.5' : ''}">
      <div class="row between"><span class="name">${esc(c.name)}</span><span class="pill ${c.status}">${esc(statusTitle(c.status))}</span></div>
      <div class="sub" style="max-width:none">${esc(c.rubrics.slice(0, 2).join(', ') || c.niche)}${c.district ? ', ' + esc(c.district) : ''}</div>
      <div>${contactIcons(c)}</div>
      <div class="reason"><b>${esc(c.segment)}</b>${esc(c.segment_reason)}</div>
      <div class="muted small">${c.rating ? '★ ' + c.rating : ''} ${c.reviews ? c.reviews + ' ' + plural(c.reviews, 'отзыв', 'отзыва', 'отзывов') : ''}</div></div>`).join('')}</div>${pager}`;
  } else {
    body.innerHTML = `<div style="overflow-x:auto"><table><thead><tr>${cols.map(([k, t]) => `<th data-sort="${k}" class="${b.sort === k ? 'sorted' : ''}">${t}${b.sort === k ? (b.dir === 'asc' ? ' ↑' : ' ↓') : ''}</th>`).join('')}</tr></thead>
      <tbody>${data.items.map((c) => `<tr data-id="${c.id}" class="${c.not_my_client ? 'nmc' : ''}">
        <td><div class="name">${esc(c.name)}</div><div class="sub">${esc(c.rubrics.slice(0, 2).join(', ') || c.niche)}</div></td>
        <td style="max-width:210px">${contactIcons(c)}</td>
        <td class="muted">${esc(c.district || c.city)}</td>
        <td style="white-space:nowrap">${c.reviews || '—'}${c.rating ? `<span class="muted small"> ★ ${c.rating}</span>` : ''}</td>
        <td><div class="reason"><b>${esc(c.segment)}</b>${esc(c.segment_reason)}</div></td>
        <td><span class="pill ${c.status}">${esc(statusTitle(c.status))}</span></td></tr>`).join('')}</tbody></table></div>${pager}`;
    $$('th[data-sort]', body).forEach((th) => { th.onclick = () => { const k = th.dataset.sort; if (!k) return; b.dir = b.sort === k && b.dir === 'desc' ? 'asc' : 'desc'; b.sort = k; loadBase(); }; });
  }
  $$('[data-id]', body).forEach((el) => { el.onclick = () => openCompany(+el.dataset.id); });
  $('#prev').onclick = () => { b.page--; loadBase(); }; $('#next').onclick = () => { b.page++; loadBase(); };
});

/* ---------- карточка компании ---------- */
function fillTemplate(body, c) {
  const map = { 'название': c.name, 'отзывы': c.reviews || 0, 'сайт': (c.site || '').replace(/^https?:\/\//, ''), 'проблема': (c.segment_reason || '').replace(/^./, (ch) => ch.toLowerCase()),
    'город': c.city, 'рейтинг': c.rating || '', 'район': c.district, 'ниша': c.niche };
  return body.replace(/\{([а-яё]+)\}/gi, (m, key) => (key.toLowerCase() in map ? map[key.toLowerCase()] : m));
}
const openCompany = guard(async (id) => {
  const [c, templates] = await Promise.all([api('/api/companies/' + id), api('/api/templates')]);
  S.templates = templates;
  const link = (url, text) => `<a data-open="${esc(url)}" href="${esc(url)}">${esc(text || url.replace(/^https?:\/\//, ''))}</a>`;
  const rows = [];
  if (c.phones.length) rows.push(['Телефон', c.phones.map((p) => link('tel:+' + p, phoneFmt(p))).join('<br>')]);
  if (c.telegram) rows.push(['Telegram', link(c.telegram)]);
  if (c.whatsapp) rows.push(['WhatsApp', link(c.whatsapp)]);
  if (c.max) rows.push(['MAX', link(c.max)]);
  if (c.vk) rows.push(['VK', link(c.vk)]);
  if (c.instagram) rows.push(['Instagram', link(c.instagram)]);
  if (c.emails.length) rows.push(['E-mail', c.emails.map((e) => link('mailto:' + e, e)).join('<br>')]);
  if (c.site) rows.push(['Сайт', link(c.site) + (c.site_found_by === 'search' ? ' <span class="muted small">найден через поиск</span>' : '')]);
  if (c.address) rows.push(['Адрес', esc([c.city, c.district, c.address].filter(Boolean).join(', '))]);
  if (c.hours) rows.push(['Часы работы', esc(c.hours)]);
  if (c.booking) rows.push(['Онлайн-запись', esc(c.booking)]);
  const cardNames = { '2gis': '2ГИС', yandex_maps: 'Яндекс Карты', yandex_search: 'Сайт из поиска' };
  const cards = Object.entries(c.card_urls).map(([k, u]) => link(u, cardNames[k] || k)).join(' · ');
  if (cards) rows.push(['Карточки', cards]);
  const yes = (v, t) => `<span class="badge ${v ? 'yes' : 'no'}">${v ? '✓' : '✕'} ${t}</span>`;
  const siteBlock = !c.site ? '' : c.site_status === 'ok'
    ? `<div class="badges">${yes(c.site_ssl, 'SSL')}${yes(c.site_mobile, 'мобильная версия')}${yes(c.site_form, 'форма заявки')}${yes(c.site_calc, 'калькулятор')}${yes(c.site_booking, 'онлайн-запись')}${yes(c.site_chat, 'чат')}${c.site_year ? `<span class="badge">год в подвале: ${c.site_year}</span>` : ''}</div>`
    : c.site_status === 'down' ? `<div class="badges"><span class="badge no">✕ сайт не открывается: ${esc(c.site_error)}</span></div>`
    : c.site_status === 'unknown' ? `<div class="badges"><span class="badge">${esc(c.site_error)}</span></div>` : '<p class="muted small">Сайт ещё не проверялся.</p>';
  const d = $('#drawer');
  d.innerHTML = `
    <div class="row"><div class="grow"><h1>${esc(c.name)}</h1><p class="muted">${esc(c.rubrics.join(', ') || c.niche)}${c.rating ? ` · ★ ${c.rating}` : ''}${c.reviews ? ` · ${c.reviews} ${plural(c.reviews, 'отзыв', 'отзыва', 'отзывов')}` : ''}</p></div>
      <button class="btn ghost x" id="close" title="Закрыть">✕</button></div>
    <div class="why"><b>${esc(c.segment)}</b><br>${esc(c.segment_reason)}${c.reasons.length > 1 ? `<div class="muted small" style="margin-top:6px">${c.reasons.filter((r) => r !== c.segment_reason).map(esc).join('<br>')}</div>` : ''}</div>
    <div class="sect"><h2>Статус</h2><div class="statuses">${S.meta.statuses.map((s) => `<button data-status="${s.key}" class="${c.status === s.key ? 'on' : ''}">${esc(s.title)}</button>`).join('')}</div></div>
    <div class="sect"><h2>Контакты</h2><dl class="contacts">${rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('')}</dl></div>
    ${siteBlock ? `<div class="sect"><h2>Проверка сайта</h2>${siteBlock}</div>` : ''}
    <div class="sect"><h2>Сообщение</h2>
      <div class="row" style="margin-bottom:8px"><select id="tpl"><option value="">${c.message ? 'Готовое сообщение из импорта' : 'Выберите шаблон'}</option>${templates.map((t) => `<option value="${t.id}">${esc(t.name)}</option>`).join('')}</select></div>
      <textarea id="msg" rows="5" placeholder="Выберите шаблон или напишите сообщение">${esc(c.message)}</textarea>
      <div class="row wrap" style="margin-top:8px"><button class="btn primary" id="copy">Скопировать сообщение</button>
        ${c.telegram ? `<button class="btn" data-open="${esc(c.telegram)}">Открыть чат в Telegram</button>` : ''}
        ${c.whatsapp ? `<button class="btn" data-open="${esc(c.whatsapp)}">Открыть чат в WhatsApp</button>` : ''}
        ${c.max ? `<button class="btn" data-open="${esc(c.max)}">Открыть MAX</button>` : ''}</div>
      <p class="muted small" style="margin-top:8px">Сообщения отправляете вы сами: программа только копирует текст и открывает чат.</p></div>
    <div class="sect"><h2>Заметки и следующее касание</h2>
      <textarea id="notes" rows="3" placeholder="Что обсуждали, о чём договорились">${esc(c.notes)}</textarea>
      <div class="row" style="margin-top:8px"><label class="f" style="width:190px">Написать повторно<input type="date" id="touch" value="${esc(c.next_touch)}"></label><span class="muted small grow" id="saved"></span></div></div>
    <div class="sect"><h2>История статусов</h2><div class="history">${c.history.map((h) => `<span>${dateFmt(h.at)}</span><span>${esc(statusTitle(h.status))}</span>`).join('')}</div></div>
    <div class="row between"><span class="muted small">ID ${c.id} · добавлена ${dateFmt(c.created_at)}</span><button class="btn sm danger ghost" id="del">Удалить из базы</button></div>`;
  $('#drawer-wrap').hidden = false;
  const refresh = () => { refreshCounters(); if (VIEWS[S.view] && S.view !== 'collect') VIEWS[S.view](); };
  const save = guard(async (fields) => { await api('/api/companies/' + id, fields, 'PATCH'); $('#saved').textContent = 'Сохранено'; setTimeout(() => { if ($('#saved')) $('#saved').textContent = ''; }, 1500); });
  $('#close').onclick = closeDrawer;
  $$('[data-status]', d).forEach((b) => { b.onclick = guard(async () => { await api(`/api/companies/${id}/status`, { status: b.dataset.status }); await openCompany(id); refresh(); }); });
  $('#tpl').onchange = (e) => { const t = templates.find((x) => String(x.id) === e.target.value); $('#msg').value = t ? fillTemplate(t.body, c) : c.message; if (t) { c.message = $('#msg').value; save({ message: c.message }); } };
  $('#msg').onchange = (e) => save({ message: e.target.value });
  $('#copy').onclick = async () => { const text = $('#msg').value.trim(); if (!text) return toast('Сначала выберите шаблон или напишите текст.', 'error'); await copyText(text); toast('Сообщение скопировано'); };
  $('#notes').onchange = (e) => save({ notes: e.target.value });
  $('#touch').onchange = async (e) => { await save({ next_touch: e.target.value }); refreshCounters(); };
  $('#del').onclick = guard(async () => { if (!confirm(`Удалить «${c.name}» из базы?`)) return; await api('/api/companies/delete', { ids: [id] }); closeDrawer(); toast('Компания удалена'); refresh(); });
});
function closeDrawer() { $('#drawer-wrap').hidden = true; }
$('.drawer-shade').onclick = closeDrawer;
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeDrawer(); });

/* ---------- воронка ---------- */
VIEWS.funnel = guard(async () => {
  const data = await api('/api/companies?hide_nmc=1&sort=status_changed_at&dir=desc&limit=2000');
  const by = {}; data.items.forEach((c) => { (by[c.status] = by[c.status] || []).push(c); });
  main.innerHTML = `<div class="view"><div class="head"><div><h1>Воронка</h1><p>Перетаскивайте компании между колонками — статус и дата сохранятся.</p></div></div>
    <div class="board">${S.meta.statuses.map((s) => `<div class="col" data-col="${s.key}"><div class="col-head">${esc(s.title)}<span>${(by[s.key] || []).length}</span></div>
      <div class="col-body">${(by[s.key] || []).slice(0, 150).map((c) => `<div class="kcard" draggable="true" data-id="${c.id}"><b>${esc(c.name)}</b><small>${esc(c.segment)}${c.next_touch ? ' · ' + dateFmt(c.next_touch) : ''}</small></div>`).join('')
        || '<span class="muted small" style="padding:6px">Пусто</span>'}</div></div>`).join('')}</div></div>`;
  let dragged = null;
  $$('.kcard').forEach((el) => {
    el.onclick = () => openCompany(+el.dataset.id);
    el.ondragstart = (e) => { dragged = el; el.classList.add('drag'); e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', el.dataset.id); };
    el.ondragend = () => { el.classList.remove('drag'); $$('.col.over').forEach((c) => c.classList.remove('over')); };
  });
  $$('.col').forEach((col) => {
    col.ondragover = (e) => { e.preventDefault(); col.classList.add('over'); };
    col.ondragleave = (e) => { if (!col.contains(e.relatedTarget)) col.classList.remove('over'); };
    col.ondrop = guard(async (e) => {
      e.preventDefault();
      const id = e.dataTransfer.getData('text/plain') || (dragged && dragged.dataset.id);
      if (!id || (dragged && dragged.closest('.col') === col)) return col.classList.remove('over');
      await api(`/api/companies/${id}/status`, { status: col.dataset.col });
      refreshCounters(); VIEWS.funnel();
    });
  });
});

/* ---------- сегодня ---------- */
VIEWS.today = guard(async () => {
  const t = await api('/api/today');
  const s = S.settings;
  const block = (title, hint, items) => `<div class="card"><h2>${title} <span class="muted">${items.length}</span></h2><p class="muted small" style="margin:-6px 0 8px">${hint}</p>
    ${items.length ? items.map((c) => `<div class="list-item" data-id="${c.id}"><div class="grow"><div class="name">${esc(c.name)}</div><div class="sub" style="max-width:none">${esc(c.segment_reason)}</div></div>
      <div>${contactIcons(c)}</div><span class="muted small" style="white-space:nowrap">${dateFmt(c.status_changed_at).slice(0, 10)}</span><span class="pill ${c.status}">${esc(statusTitle(c.status))}</span></div>`).join('')
      : '<p class="muted small">Никого.</p>'}</div>`;
  const total = t.planned.length + t.read_silent.length + t.no_reply.length;
  main.innerHTML = `<div class="view" style="max-width:980px"><div class="head"><div><h1>Сегодня</h1><p>${total ? `Написать повторно: ${total}` : 'На сегодня повторных касаний нет.'}</p></div></div><div class="stack">
    ${block('Запланировано на сегодня', 'Дата следующего касания наступила.', t.planned)}
    ${block('Прочитали и молчат', `Статус «Прочитал» держится ${s.read_silent_days} дн. и дольше.`, t.read_silent)}
    ${block('Нет ответа', `Статус «Написал» держится ${s.no_reply_days} дн. и дольше.`, t.no_reply)}</div></div>`;
  $$('.list-item').forEach((el) => { el.onclick = () => openCompany(+el.dataset.id); });
});

/* ---------- экспорт ---------- */
VIEWS.export = function () {
  const x = S.exp;
  if (!x.fields) x.fields = S.meta.export_fields.map((f) => f.key).filter((k) => !['reasons', 'niche', 'created_at', 'status_changed_at', 'not_my_client'].includes(k));
  const activeFilters = Object.keys(baseFilters()).length;
  main.innerHTML = `<div class="view" style="max-width:1000px"><div class="head"><div><h1>Экспорт и импорт</h1><p>Файлы сохраняются в папку программы — после выгрузки её можно открыть одной кнопкой.</p></div></div><div class="stack">
    <div class="card stack">
      <div class="row between wrap"><h2 style="margin:0">Выгрузить базу</h2><div class="seg" id="fmt">${[['xlsx', 'Excel'], ['csv', 'CSV'], ['json', 'JSON']].map(([k, t]) => `<button data-fmt="${k}" class="${x.format === k ? 'on' : ''}">${t}</button>`).join('')}</div></div>
      <label class="check"><input type="checkbox" id="use-f" ${x.useFilters ? 'checked' : ''}>Только то, что отобрано фильтрами на экране «База» ${activeFilters ? `<span class="muted">(включено фильтров: ${activeFilters})</span>` : '<span class="muted">(сейчас фильтров нет — выгрузится всё)</span>'}</label>
      <div><div class="row between" style="margin-bottom:8px"><span class="muted small">Поля</span><span class="row"><a id="all-f">все</a><a id="none-f">ничего</a></span></div>
        <div class="fields">${S.meta.export_fields.map((f) => `<label class="check"><input type="checkbox" data-field="${f.key}" ${x.fields.includes(f.key) ? 'checked' : ''} ${f.key === 'id' ? 'disabled checked' : ''}>${esc(f.title)}</label>`).join('')}</div></div>
      <div class="row wrap"><button class="btn primary" id="do-export">Выгрузить</button><button class="btn" id="do-claude">Экспорт для Claude</button>
        <span class="muted small grow">«Экспорт для Claude» — JSON со всеми полями, сегментом и причиной. Отправьте файл Claude и попросите написать сообщения.</span></div>
      <div id="exp-result"></div></div>
    <div class="card stack"><h2 style="margin:0">Импортировать обратно</h2>
      <p class="muted">Файл CSV, JSON или Excel со столбцом ID. По ID обновятся сообщение, заметки, статус, дата касания и контакты — остальное не трогается.</p>
      <div class="row"><input type="file" id="imp-file" accept=".csv,.json,.xlsx" hidden><button class="btn" id="imp-btn">Выбрать файл</button><span class="muted small" id="imp-result"></span></div></div></div></div>`;
  $('#fmt').onclick = (e) => { if (e.target.dataset.fmt) { x.format = e.target.dataset.fmt; $$('#fmt button').forEach((b) => b.classList.toggle('on', b === e.target)); } };
  $('#use-f').onchange = (e) => { x.useFilters = e.target.checked; };
  const readFields = () => { x.fields = $$('[data-field]:checked').map((el) => el.dataset.field); };
  $$('[data-field]').forEach((el) => { el.onchange = readFields; });
  $('#all-f').onclick = () => { $$('[data-field]').forEach((el) => { el.checked = true; }); readFields(); };
  $('#none-f').onclick = () => { $$('[data-field]:not(:disabled)').forEach((el) => { el.checked = false; }); readFields(); };
  const run = (claude) => guard(async () => {
    const r = await api('/api/export', { format: x.format, fields: x.fields, filters: x.useFilters ? baseFilters() : {}, claude });
    $('#exp-result').innerHTML = `<div class="alert"><div class="grow"><b>Выгружено: ${r.count}</b><div class="small" style="word-break:break-all">${esc(r.path)}</div></div><button class="btn" id="open-dir">Открыть папку</button><button class="btn" id="copy-path">Скопировать путь</button></div>`;
    $('#open-dir').onclick = () => openFolder(r.path);
    $('#copy-path').onclick = async () => { await copyText(r.path); toast('Путь скопирован'); };
  });
  $('#do-export').onclick = run(false); $('#do-claude').onclick = run(true);
  $('#imp-btn').onclick = () => $('#imp-file').click();
  $('#imp-file').onchange = guard(async (e) => {
    const file = e.target.files[0]; if (!file) return;
    const res = await fetch('/api/import?filename=' + encodeURIComponent(file.name), { method: 'POST', headers: TOKEN, body: await file.arrayBuffer() });
    const data = await res.json(); e.target.value = '';
    if (!res.ok) throw new Error(data.error || 'Импорт не удался');
    $('#imp-result').textContent = `Обновлено: ${data.updated}` + (data.skipped ? `, пропущено строк без подходящего ID: ${data.skipped}` : '');
    refreshCounters();
  });
};

/* ---------- настройки ---------- */
VIEWS.settings = guard(async () => {
  const [s, templates, meta] = await Promise.all([api('/api/settings'), api('/api/templates'), api('/api/meta')]);
  S.settings = s; S.meta = meta;
  const num = (key, label, step) => `<label class="f">${label}<input type="number" data-set="${esc(key)}" value="${esc(s[key])}" step="${esc(step || 1)}" min="0"></label>`;
  main.innerHTML = `<div class="view" style="max-width:1000px"><div class="head"><div><h1>Настройки</h1></div><button class="btn primary" id="save-set">Сохранить настройки</button></div><div class="stack">
    <div class="card"><h2>Вежливый режим</h2><p class="muted" style="margin:-6px 0 14px">Сбор идёт в одном окне браузера с паузами, как у человека. Чем спокойнее темп, тем реже источники просят капчу.</p>
      <div class="form-grid">${num('delay_min', 'Пауза между страницами, от (сек)', 0.5)}${num('delay_max', 'Пауза между страницами, до (сек)', 0.5)}${num('cards_per_hour', 'Страниц в час, не больше')}${num('max_pages', 'Страниц выдачи на запрос')}${num('page_timeout', 'Ждать загрузку страницы (сек)')}
        <label class="f">Браузер<select data-set="browser"><option value="auto">Автовыбор</option><option value="chromium">Chromium из Playwright</option><option value="msedge">Microsoft Edge</option><option value="chrome">Google Chrome</option></select></label></div></div>
    <div class="card"><h2>Пороги</h2><div class="form-grid">${num('many_reviews', '«Много отзывов» — от')}${num('read_silent_days', 'Прочитал и молчит (дней)')}${num('no_reply_days', 'Нет ответа (дней)')}${num('old_site_years', 'Сайт устарел, если году в подвале (лет)')}${num('network_branches', 'Сеть — от скольких филиалов')}</div></div>
    <div class="card"><h2>Не мой клиент</h2><p class="muted" style="margin:-6px 0 10px">Компании, в названии или рубриках которых есть эти слова, помечаются и уходят из воронки. По одному слову или фразе в строке.</p>
      <textarea id="stop-words" rows="6">${esc(s.stop_words.join('\n'))}</textarea></div>
    <div class="card"><div class="row between" style="margin-bottom:12px"><h2 style="margin:0">Шаблоны сообщений</h2><button class="btn sm" id="tpl-add">Добавить шаблон</button></div>
      <p class="muted small" style="margin-bottom:12px">Подстановки: {название}, {отзывы}, {сайт}, {проблема}, {город}, {район}, {рейтинг}, {ниша}.</p>
      <div class="stack" id="tpls">${templates.map((t) => tplForm(t)).join('')}</div></div>
    <div class="card stack"><h2 style="margin:0">База и резервная копия</h2>
      <div><div class="muted small" style="margin-bottom:6px">Файл базы</div><div class="path">${esc(meta.paths.db)}</div></div>
      <div class="row"><input type="text" id="data-dir" placeholder="Новая папка для базы, например D:\\Сборщик" value=""><button class="btn" id="move-db">Перенести базу</button></div>
      <div class="row wrap"><button class="btn" id="backup">Сделать резервную копию</button><button class="btn ghost" id="open-data">Открыть папку базы</button><span class="muted small" id="backup-result"></span></div></div>
    <div class="card stack"><h2 style="margin:0">Если источник перестал собираться</h2>
      <p class="muted">Сайты иногда меняют вёрстку. Селекторы лежат в отдельном файле: скопируйте встроенный файл в папку ниже, поправьте — программа возьмёт вашу версию. Подробности в README.</p>
      <div><div class="muted small" style="margin-bottom:6px">Встроенный файл селекторов</div><div class="path">${esc(meta.paths.selectors.builtin)}</div></div>
      <div><div class="muted small" style="margin-bottom:6px">Ваша версия ${meta.paths.selectors.custom_exists ? '(используется сейчас)' : '(пока не создана)'}</div><div class="path">${esc(meta.paths.selectors.custom)}</div></div>
      <div><div class="muted small" style="margin-bottom:6px">Журнал работы</div><div class="path">${esc(meta.paths.log)}</div></div></div></div></div>`;
  $('[data-set=browser]').value = s.browser;
  $('#save-set').onclick = guard(async () => {
    const body = { stop_words: $('#stop-words').value.split('\n').map((x) => x.trim()).filter(Boolean) };
    $$('[data-set]').forEach((el) => { body[el.dataset.set] = el.type === 'number' ? Number(el.value) : el.value; });
    S.settings = await api('/api/settings', body); toast('Настройки сохранены'); refreshCounters();
  });
  $('#backup').onclick = guard(async () => { const r = await api('/api/backup', {}); $('#backup-result').textContent = 'Копия сохранена: ' + r.path; });
  $('#open-data').onclick = () => openFolder(meta.paths.db);
  $('#move-db').onclick = guard(async () => { const r = await api('/api/settings/data_dir', { path: $('#data-dir').value }); toast('База перенесена: ' + r.db); VIEWS.settings(); });
  $('#tpl-add').onclick = () => { $('#tpls').insertAdjacentHTML('beforeend', tplForm({ id: '', name: '', body: '' })); };
  $('#tpls').onclick = guard(async (e) => {
    const box = e.target.closest('[data-tpl]'); if (!box) return;
    if (e.target.dataset.act === 'save') { await api('/api/templates', { id: +box.dataset.tpl || null, name: $('input', box).value, body: $('textarea', box).value }); toast('Шаблон сохранён'); VIEWS.settings(); }
    if (e.target.dataset.act === 'del') { if (box.dataset.tpl) await api('/api/templates/' + box.dataset.tpl, undefined, 'DELETE'); box.remove(); }
  });
});
const tplForm = (t) => `<div data-tpl="${t.id}" class="stack" style="gap:8px"><div class="row"><input type="text" placeholder="Название шаблона" value="${esc(t.name)}"><button class="btn sm" data-act="save">Сохранить</button><button class="btn sm ghost danger" data-act="del">Удалить</button></div><textarea rows="3" placeholder="Текст сообщения">${esc(t.body)}</textarea></div>`;

/* ---------- запуск ---------- */
(async function init() {
  try {
    [S.meta, S.settings] = await Promise.all([api('/api/meta'), api('/api/settings')]);
  } catch (e) { main.innerHTML = `<div class="empty"><b>Приложение не отвечает</b>${esc(e.message)}</div>`; return; }
  $('#side-foot').textContent = 'Данные хранятся только на этом компьютере';
  await poll();
  await refreshCounters();
  go(S.job && S.job.status === 'idle' && !S.job.resumable && S.facets && S.facets.total ? 'base' : 'collect');
})();
