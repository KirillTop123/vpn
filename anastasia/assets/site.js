/* Сайт Анастасии Губайдулиной: все тексты, цены, фото и отзывы берутся из data.js (редактируется в admin.html) */
(function () {
  "use strict";
  document.documentElement.classList.add("js");
  const RM = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const PAGE = document.body.dataset.page || "home";
  const FILTER_SVG = `<svg width="0" height="0" style="position:absolute" aria-hidden="true">
  <!-- линза liquid glass: карта смещения + хроматическая аберрация (адаптация liquid-glass-react) -->
  <filter id="lg" x="-10%" y="-10%" width="120%" height="120%" color-interpolation-filters="sRGB">
    <feTurbulence type="fractalNoise" baseFrequency="0.008 0.012" numOctaves="2" seed="7" result="map"/>
    <feDisplacementMap in="SourceGraphic" in2="map" scale="22" xChannelSelector="R" yChannelSelector="B" result="r"/>
    <feColorMatrix in="r" type="matrix" values="1 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1 0" result="rr"/>
    <feDisplacementMap in="SourceGraphic" in2="map" scale="20" xChannelSelector="R" yChannelSelector="B" result="g"/>
    <feColorMatrix in="g" type="matrix" values="0 0 0 0 0  0 1 0 0 0  0 0 0 0 0  0 0 0 1 0" result="gg"/>
    <feDisplacementMap in="SourceGraphic" in2="map" scale="18" xChannelSelector="R" yChannelSelector="B" result="b"/>
    <feColorMatrix in="b" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 1 0 0  0 0 0 1 0" result="bb"/>
    <feBlend in="rr" in2="gg" mode="screen" result="rg"/>
    <feBlend in="rg" in2="bb" mode="screen"/>
  </filter>
</svg>`;
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const esc = (v) => String(v == null ? "" : v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmt = (n) => Number(n).toLocaleString("ru-RU").replace(/ /g, " ") + " ₽";
  const LEN = { s: "короткие", m: "средние", l: "длинные" };
  const isObj = (p) => p && typeof p === "object";
  const priceFrom = (p) => (isObj(p) ? Math.min(...Object.values(p).map(Number)) : Number(p));
  const priceLabel = (p, l) => (isObj(p) ? (l ? fmt(p[l]) : "от " + fmt(priceFrom(p))) : fmt(p));
  const tel = (p) => "tel:+" + String(p).replace(/\D/g, "").replace(/^8/, "7");
  const dateRu = (d) => { try { return new Date(d + "T12:00:00").toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" }); } catch (_) { return d; } };
  const ICON = {
    cal: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="3"/><path d="M3 10h18M8 3v4M16 3v4"/></svg>',
    phone: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M5 4h4l2 5-2.5 1.5a11 11 0 005 5L15 13l5 2v4a2 2 0 01-2 2A16 16 0 013 6a2 2 0 012-2"/></svg>',
    pin: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="M12 21s-7-6.2-7-11.5A7 7 0 0119 9.5C19 14.8 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.5"/></svg>',
    clock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
    chat: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="M21 12a8 8 0 01-11.6 7.1L4 20l1.1-4.6A8 8 0 1121 12z"/></svg>',
    star: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 2.5l2.9 6.1 6.6.8-4.9 4.6 1.3 6.6L12 17.3 6.1 20.6l1.3-6.6L2.5 9.4l6.6-.8z"/></svg>',
    menu: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M4 8h16M4 16h16"/></svg>',
    award: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><circle cx="12" cy="9" r="6"/><path d="M8.5 14.5L7 22l5-3 5 3-1.5-7.5"/></svg>',
  };
  const PAGES = [
    ["home", "index.html", "Главная"],
    ["uslugi", "uslugi.html", "Услуги и цены"],
    ["raboty", "raboty.html", "Работы"],
    ["otzyvy", "otzyvy.html", "Отзывы"],
    ["kontakty", "kontakty.html", "Контакты"],
  ];

  // ---------- данные: опубликованные или черновик из админки (?preview=1) ----------
  function loadData(cb) {
    if (/[?&]preview=1/.test(location.search)) {
      try {
        const d = JSON.parse(localStorage.getItem("gub_draft") || "null");
        if (d) return cb(d, true);
      } catch (_) {}
    }
    if (window.SITE_DATA) return cb(window.SITE_DATA, false);
    const s = document.createElement("script");
    s.src = "data.js?v=" + Date.now(); // без кеша: правки из админки видны сразу после публикации
    s.onload = () => cb(window.SITE_DATA || {}, false);
    s.onerror = () => cb({}, false);
    document.head.appendChild(s);
  }

  loadData(function (D, preview) {
    const P = D.profile || {};
    const booking = P.booking || "#";
    document.body.insertAdjacentHTML("afterbegin", FILTER_SVG);

    // ---------- шапка, меню, низ ----------
    let top = "";
    if (preview) top += '<div class="announce" style="background:#7a5cff;color:#fff">Предпросмотр черновика из админ-панели — посетители его не видят</div>';
    else if (D.announcement && D.announcement.on && D.announcement.text)
      top += `<a class="announce" ${D.announcement.link ? `href="${esc(D.announcement.link)}"` : ""}>${esc(D.announcement.text)}</a>`;
    if (top) document.body.classList.add("has-announce");
    const navLinks = PAGES.slice(1).map(([id, href, t]) => `<a class="l${id === PAGE ? " on" : ""}" href="${href}">${t}</a>`).join("");
    document.body.insertAdjacentHTML(
      "afterbegin",
      top +
        `<header class="nav glass lens" id="nav"><a class="brand" href="index.html">${esc(P.short || P.name)}</a>${navLinks}
<button class="btn gold" data-book>Записаться</button><button class="burger" aria-label="Меню" data-menu>${ICON.menu}</button></header>
<div class="mmenu" id="mmenu" role="dialog" aria-modal="true" aria-label="Меню"><button class="x glass" aria-label="Закрыть" data-menu>✕</button>
${PAGES.map(([id, href, t]) => `<a href="${href}" class="${id === PAGE ? "on" : ""}">${t}</a>`).join("")}
<div class="sub">${esc(P.address || "")}<br><a href="${tel(P.phone)}">${esc(P.phone || "")}</a></div></div>`
    );
    document.body.insertAdjacentHTML(
      "beforeend",
      `<footer><div class="wrap"><span>© ${esc(P.name)} · ${esc((P.title || "").toLowerCase())} · ${esc(P.city || "")}</span>
<span>${PAGES.map(([, h, t]) => `<a href="${h}">${t}</a>`).join(" · ")}</span><span>Работаю на ${esc(P.brand || "")}</span></div></footer>
<nav class="dockbar glass lens away" id="dock" aria-label="Быстрая запись"><button class="btn gold" data-book>Записаться</button>
<a class="btn ghost call" href="${tel(P.phone)}" aria-label="Позвонить">${ICON.phone}</a></nav>
<div class="lb" id="lb" role="dialog" aria-modal="true" aria-label="Просмотр работы"><button class="x glass" aria-label="Закрыть">✕</button><button class="p glass" aria-label="Предыдущая">‹</button><img alt=""><button class="n glass" aria-label="Следующая">›</button></div>
<div class="toast glass" id="toast" role="status"></div>`
    );

    // ---------- страницы ----------
    const main = $("#app");
    const R = { home, uslugi, raboty, otzyvy, kontakty };
    main.innerHTML = (R[PAGE] || home)();
    if (PAGE === "home") initShader();
    initServicesPage();
    initGallery();
    initUI();
    initReveal();
    jsonLd();
    if (preview) $$('a[href$=".html"], a[href*=".html#"]').forEach((a) => { const [u, h] = a.getAttribute("href").split("#"); a.setAttribute("href", u + "?preview=1" + (h ? "#" + h : "")); });

    function head(eyebrow, title, lead) {
      return `<section class="phead"><div class="wrap"><p class="crumbs"><a href="index.html">Главная</a> · ${esc(eyebrow)}</p>
<h1>${title}</h1>${lead ? `<p class="lead">${lead}</p>` : ""}</div></section>`;
    }
    function rating() {
      return `<div class="badge glass"><span class="star" aria-hidden="true">★</span><b>${esc(P.rating)}</b> ${esc(P.ratingCount)} оценки · ${esc(P.award)}</div>`;
    }
    function ctaRow() {
      return `<div class="cta"><button class="btn gold" data-book>${ICON.cal}Записаться онлайн</button><a class="btn ghost" href="${tel(P.phone)}">${esc(P.phone)}</a></div>`;
    }
    function specCards(list) {
      return list
        .map((s) => `<a class="spec rv" href="uslugi.html#${esc(s.id)}"><img src="${esc(s.img)}" alt="${esc(s.name)}" loading="lazy"><div class="t"><small>${esc(s.tag || "")}</small><h3>${esc(s.tag && s.tag !== s.name && s.name.length > 22 ? s.tag : s.name)}</h3><p>${esc(s.desc)}</p><span class="from glass">${priceLabel(s.price)}</span></div></a>`)
        .join("");
    }
    function workFigs(list) {
      return list.map((w) => `<figure data-c="${esc((w.cats || []).join(" "))}"><img src="${esc(w.img)}" alt="${esc(w.alt || w.caption || "Работа мастера")}" loading="lazy">${w.caption ? `<figcaption class="glass">${esc(w.caption)}</figcaption>` : ""}</figure>`).join("");
    }
    function reviewCards(list) {
      if (!list.length) return '<div class="empty">Отзывы появятся здесь</div>';
      return `<div class="revs">${list
        .map((r) => `<article class="rev glass rv"><span class="st" aria-label="Оценка ${esc(r.rating)} из 5">${"★".repeat(r.rating || 5)}</span><q>${esc(r.text)}</q><div class="who"><i>${esc((r.name || "?")[0])}</i><div>${esc(r.name)}<small>${esc(dateRu(r.date))} · ${esc(r.source || "")}</small></div></div></article>`)
        .join("")}</div>`;
    }
    function ratingBlock() {
      const st = (D.reviewStats || []).map((k) => `<span>${esc(k.name)} · <b>${esc(k.value)}</b> положительных</span>`).join("");
      return `<p class="eyebrow">Яндекс Карты</p><div class="big" style="margin-top:24px">${esc(P.rating)}</div>
<div class="stars" aria-label="Рейтинг ${esc(P.rating)} из 5">${ICON.star.repeat(5)}</div>
<p class="lead" style="margin:0 auto">${esc(P.ratingCount)} оценки и ${esc(P.reviewsCount)} отзыв клиентов</p>
<div class="award glass">${ICON.award}Знак «${esc(P.award)}»</div>${st ? `<div class="kpi">${st}</div>` : ""}`;
    }

    function home() {
      const feat = (D.services || []).filter((s) => s.featured && s.img && !s.hidden).slice(0, 4);
      const fw = (D.works || []).filter((w) => w.featured).slice(0, 8);
      const nm = (P.name || "").split(" ");
      return `<section class="hero"><canvas id="shader" aria-hidden="true"></canvas><div class="grain" aria-hidden="true"></div><div class="wrap"><div>${rating()}
<h1><span>${esc(nm[0])}</span><span class="ln2"><em>${esc(nm.slice(1).join(" "))}</em></span></h1><p class="lead">${esc(P.heroText)}</p>${ctaRow()}</div>
<figure class="portrait"><img src="${esc(P.heroImg)}" alt="${esc(P.heroCaption || "Работа мастера")}" fetchpriority="high"><figcaption class="tag glass"><b>${esc(P.heroCaption)}</b>работа мастера</figcaption></figure></div><span class="scrollcue" aria-hidden="true"></span></section>
<div class="ribbon" aria-hidden="true"><div class="track" id="rib">${(D.services || []).filter((s) => s.tag).map((s) => `<span>${esc(s.tag)}</span><i>✦</i>`).join("")}<span>${esc(P.brand)}</span><i>✦</i><span>Укладка</span><i>✦</i><span>Косметическая стрижка</span><i>✦</i></div></div>
<section class="about" id="about"><div class="wrap grid"><div class="stack rv"><figure class="f1"><img src="img/w-blonde-waves.webp" alt="Тёплый блонд с волнами" loading="lazy"></figure><figure class="f2"><img src="img/w-brown-long.webp" alt="Гладкий каштан" loading="lazy"></figure></div>
<div class="rv"><p class="eyebrow">О мастере</p><h2 style="margin:18px 0 24px">${esc(P.aboutTitle).replace(/(\S+\s\S+)$/, "<em>$1</em>")}</h2>${(P.about || []).map((t) => `<p class="lead">${esc(t)}</p>`).join("")}
<div class="facts"><div><b>${esc(P.rating)}</b><span>рейтинг на Яндекс Картах</span></div><div><b>${(D.services || []).filter((s) => !s.hidden).length}</b><span>услуг в прайсе</span></div><div><b>${esc(P.reviewsCount)}</b><span>отзыв клиентов</span></div></div></div></div></section>
<section style="padding-top:0"><div class="wrap rv"><p class="eyebrow">Шкала уровней тона</p><h2 style="margin-top:18px">От <em>эспрессо</em> до шампани</h2>
<p class="lead" style="margin-top:18px">Колористы говорят на языке уровней: 1 — чёрный, 10 — самый светлый блонд. Любой переход между ними — задача формулы, а не удачи.</p>
<div class="levels" aria-label="Шкала уровней тона от 1 до 10">${["#1b1512", "#2a1e17", "#3b2a1f", "#4f3726", "#674a32", "#82603f", "#a07c53", "#bf9d6f", "#d9be92", "#eedcbc"].map((c, i) => `<div style="background:${c}"><span>${i + 1}</span></div>`).join("")}</div></div></section>
<section style="padding-top:0"><div class="wrap"><div class="spec-head rv"><div><p class="eyebrow">Специализация</p><h2 style="margin-top:18px">Что я делаю <em>лучше всего</em></h2></div><a class="btn ghost" href="uslugi.html">Все услуги и цены</a></div>
<div class="specs">${specCards(feat)}</div></div></section>
<section style="padding-top:0"><div class="wrap"><div class="spec-head rv"><div><p class="eyebrow">Портфолио</p><h2 style="margin-top:18px">Свежие <em>работы</em></h2></div><a class="btn ghost" href="raboty.html">Все работы</a></div>
<div class="masonry" id="gal">${workFigs(fw)}</div></div></section>
<section class="rating" style="padding-top:0"><div class="wrap rv">${ratingBlock()}${reviewCards((D.reviews || []).slice(0, 2))}<div style="margin-top:30px"><a class="btn ghost" href="otzyvy.html">Все отзывы</a></div></div></section>
<section style="padding-top:0"><div class="wrap"><p class="eyebrow rv">Разделы</p><div class="tiles">
<a class="tile rv" href="uslugi.html"><img src="img/w-pearl.webp" alt="" loading="lazy"><div><h3>Услуги и цены</h3><span>калькулятор по длине волос</span></div></a>
<a class="tile rv" href="raboty.html"><img src="img/w-copper.webp" alt="" loading="lazy"><div><h3>Работы</h3><span>${(D.works || []).length} фото с фильтрами</span></div></a>
<a class="tile rv" href="kontakty.html"><img src="img/i-studio.webp" alt="" loading="lazy"><div><h3>Студия и контакты</h3><span>${esc(P.address)}</span></div></a></div></div></section>`;
    }

    function uslugi() {
      const cats = D.categories || [];
      const body = cats
        .map((c) => {
          const L = (D.services || []).filter((s) => s.cat === c.id && !s.hidden);
          if (!L.length) return "";
          return `<div class="svc-cat rv"><h2>${esc(c.name)}</h2>${L.map((s) => `<div class="svc${s.img ? "" : " noimg"}" id="${esc(s.id)}">${s.img ? `<img src="${esc(s.img)}" alt="${esc(s.name)}" loading="lazy">` : ""}
<div><h3>${esc(s.name)}</h3>${s.desc ? `<p>${esc(s.desc)}</p>` : ""}</div><div class="pr"><b class="v" data-p='${esc(JSON.stringify(s.price))}'>${priceLabel(s.price, isObj(s.price) ? "m" : "")}</b>${isObj(s.price) ? '<small class="ln">средние волосы</small>' : ""}<button data-book="${esc(s.id)}">Записаться</button></div></div>`).join("")}</div>`;
        })
        .join("");
      return `${head("Услуги и цены", "Услуги <em>и цены</em>", "Цена окрашивания зависит от длины и густоты волос. Выберите длину — цены пересчитаются.")}
<section style="padding-top:0"><div class="wrap"><div class="toolbar"><div class="seg glass" role="group" aria-label="Длина волос"><button aria-pressed="false" data-l="s">Короткие</button><button aria-pressed="true" data-l="m">Средние</button><button aria-pressed="false" data-l="l">Длинные</button></div>
<span class="hint" style="margin:0">Короткие — до подбородка, средние — до плеч, длинные — ниже лопаток</span></div>${body || '<div class="empty">Услуги ещё не добавлены</div>'}
<p class="pnote">Цены указаны с карточки на Яндекс Картах и в админ-панели. Точную стоимость мастер называет после консультации.</p></div></section>
${faqBlock()}`;
    }

    function raboty() {
      const cats = D.workCats || [];
      return `${head("Портфолио", "Работы <em>из студии</em>", "Реальные результаты клиентов: окрашивания, стрижки, уход. Нажмите на фото, чтобы рассмотреть.")}
<section style="padding-top:0"><div class="wrap"><div class="chips" role="group" aria-label="Фильтр работ"><button class="chip" aria-pressed="true" data-f="all">Все</button>${cats.map((c) => `<button class="chip" aria-pressed="false" data-f="${esc(c.id)}">${esc(c.name)}</button>`).join("")}</div>
<div class="masonry" id="gal">${workFigs(D.works || [])}</div></div></section>
<section class="studio" style="padding-top:0"><div class="wrap"><div class="rv"><p class="eyebrow">Студия</p><h2 style="margin-top:18px">Светлое пространство <em>на 9 этаже</em></h2></div>
<div class="gal rv">${(D.studio || []).map((s, i) => `<figure class="${i === 0 ? "big" : ""}"><img src="${esc(s.img)}" alt="${esc(s.caption || "Студия")}" loading="lazy">${s.caption ? `<figcaption class="glass">${esc(s.caption)}</figcaption>` : ""}</figure>`).join("")}</div></div></section>`;
    }

    function otzyvy() {
      return `${head("Отзывы", "Что говорят <em>клиенты</em>", "")}
<section class="rating" style="padding-top:0"><div class="wrap rv">${ratingBlock()}${reviewCards(D.reviews || [])}
<div style="margin-top:30px"><a class="btn ghost" href="${esc(P.reviewsUrl)}" target="_blank" rel="noopener">Все ${esc(P.reviewsCount)} отзыв на Яндекс Картах</a></div></div></section>`;
    }

    function kontakty() {
      const soc = [P.telegram && `<a href="${esc(P.telegram)}" target="_blank" rel="noopener">Telegram</a>`, P.whatsapp && `<a href="https://wa.me/${esc(P.whatsapp)}" target="_blank" rel="noopener">WhatsApp</a>`, P.vk && `<a href="${esc(P.vk)}" target="_blank" rel="noopener">ВКонтакте</a>`].filter(Boolean).join("");
      return `${head("Контакты", "Жду вас <em>в студии</em>", esc(P.address) + ", " + esc(P.addressNote))}
<section class="contacts" style="padding-top:0"><div class="wrap"><div class="grid" style="margin-top:0"><div class="card glass rv"><div class="clist">
<div class="it"><span class="ic">${ICON.pin}</span><div><small>Адрес</small><p>${esc(P.address)}</p><p style="color:var(--muted);font-size:14px">${esc(P.addressNote)}</p></div></div>
<div class="it"><span class="ic">${ICON.phone}</span><div><small>Телефон</small><a href="${tel(P.phone)}">${esc(P.phone)}</a></div></div>
<div class="it"><span class="ic">${ICON.clock}</span><div><small>Время</small><p>${esc(P.hours)}</p></div></div>
${soc ? `<div class="it"><span class="ic">${ICON.chat}</span><div><small>Мессенджеры</small><div class="socials">${soc}</div></div></div>` : ""}</div>
<div class="cta"><button class="btn gold" data-book>Записаться онлайн</button><a class="btn ghost" href="${esc(P.route)}" target="_blank" rel="noopener">Маршрут</a></div></div>
<figure class="entrance rv"><img src="img/a-entrance.webp" alt="Вход в студию" loading="lazy"><figcaption class="tag glass">Вход — первый подъезд, дальше на лифте на 9 этаж</figcaption></figure></div></div></section>
${faqBlock()}`;
    }

    function faqBlock() {
      const F = D.faq || [];
      if (!F.length) return "";
      return `<section style="padding-top:0"><div class="wrap"><p class="eyebrow rv">Вопросы</p><h2 class="rv" style="margin:18px 0 26px">Частые <em>вопросы</em></h2>
<div class="faq rv">${F.map((f) => `<details><summary>${esc(f.q)}</summary><p>${esc(f.a)}</p></details>`).join("")}</div></div></section>`;
    }

    // ---------- услуги: переключатель длины ----------
    function initServicesPage() {
      const seg = $(".seg");
      if (!seg) return;
      const set = (l, anim) => {
        $$(".seg button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.l === l));
        $$(".svc .v").forEach((v) => {
          const p = JSON.parse(v.dataset.p);
          if (!isObj(p)) return;
          v.textContent = fmt(p[l]);
          const ln = v.parentNode.querySelector(".ln");
          if (ln) ln.textContent = LEN[l] + " волосы";
          if (anim) { v.classList.remove("chg"); void v.offsetWidth; v.classList.add("chg"); }
        });
      };
      seg.addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) set(b.dataset.l, true); });
      set("m");
      if (location.hash) { const t = document.getElementById(location.hash.slice(1)); if (t) setTimeout(() => t.scrollIntoView({ block: "center" }), 300); }
    }

    // ---------- портфолио: фильтр и лайтбокс ----------
    function initGallery() {
      const figs = $$("#gal figure");
      const chips = $(".chips");
      if (chips)
        chips.addEventListener("click", (e) => {
          const b = e.target.closest(".chip"); if (!b) return;
          $$(".chip").forEach((c) => c.setAttribute("aria-pressed", c === b));
          const f = b.dataset.f;
          figs.forEach((fg) => fg.classList.toggle("off", f !== "all" && !fg.dataset.c.split(" ").includes(f)));
        });
      const lb = $("#lb"), im = lb.querySelector("img"); let i = 0;
      const vis = () => [...figs, ...$$(".studio .gal figure")].filter((f) => !f.classList.contains("off"));
      const show = (k) => { const L = vis(); if (!L.length) return; i = (k + L.length) % L.length; const s = L[i].querySelector("img"); im.src = s.src; im.alt = s.alt; };
      [...figs, ...$$(".studio .gal figure")].forEach((f) => { f.style.cursor = "zoom-in"; f.addEventListener("click", () => { show(vis().indexOf(f)); lb.classList.add("on"); lb.querySelector(".x").focus(); }); });
      const close = () => lb.classList.remove("on");
      lb.addEventListener("click", (e) => { if (e.target === lb || e.target.closest(".x")) close(); if (e.target.closest(".p")) show(i - 1); if (e.target.closest(".n")) show(i + 1); });
      addEventListener("keydown", (e) => { if (!lb.classList.contains("on")) return; if (e.key === "Escape") close(); if (e.key === "ArrowLeft") show(i - 1); if (e.key === "ArrowRight") show(i + 1); });
      let x0 = null;
      lb.addEventListener("touchstart", (e) => (x0 = e.touches[0].clientX), { passive: true });
      lb.addEventListener("touchend", (e) => { if (x0 == null) return; const dx = e.changedTouches[0].clientX - x0; if (Math.abs(dx) > 50) show(i + (dx < 0 ? 1 : -1)); x0 = null; }, { passive: true });
    }

    // ---------- меню, запись, панель ----------
    function initUI() {
      const rib = $("#rib"); if (rib) rib.innerHTML += rib.innerHTML;
      const mm = $("#mmenu");
      document.addEventListener("click", (e) => {
        if (e.target.closest("[data-menu]")) { mm.classList.toggle("on"); document.body.style.overflow = mm.classList.contains("on") ? "hidden" : ""; }
        const b = e.target.closest("[data-book]");
        if (b) { e.preventDefault(); openBooking(b.dataset.book || ""); }
      });
      const nav = $("#nav"); let y0 = scrollY;
      addEventListener("scroll", () => { const y = scrollY; nav.classList.toggle("hide", y > 300 && y > y0); y0 = y; }, { passive: true });
      const d = $("#dock"), c = $(".hero .cta") || $(".phead");
      if (!("IntersectionObserver" in window) || !c) d.classList.remove("away");
      else new IntersectionObserver((e) => d.classList.toggle("away", e[0].isIntersecting)).observe(c);
    }

    function toast(t) { const el = $("#toast"); el.textContent = t; el.classList.add("on"); clearTimeout(toast.t); toast.t = setTimeout(() => el.classList.remove("on"), 2600); }

    // Запись: собирает заявку и отправляет мастеру в WhatsApp / Telegram, либо ведёт в онлайн-запись Яндекса
    function openBooking(sid) {
      let m = $("#book");
      const svcs = (D.services || []).filter((s) => !s.hidden);
      if (!m) {
        document.body.insertAdjacentHTML("beforeend", `<div class="modal" id="book" role="dialog" aria-modal="true" aria-labelledby="bk-h"><div class="sheet">
<button class="x" aria-label="Закрыть" data-close>✕</button><p class="eyebrow">Запись</p><h2 id="bk-h" style="margin:12px 0 4px">Записаться <em>к мастеру</em></h2>
<div class="fld"><label for="bk-s">Услуга</label><select id="bk-s">${(D.categories || []).map((c) => `<optgroup label="${esc(c.name)}">${svcs.filter((s) => s.cat === c.id).map((s) => `<option value="${esc(s.id)}">${esc(s.name)}</option>`).join("")}</optgroup>`).join("")}</select></div>
<div class="fld" id="bk-lw"><label for="bk-l">Длина волос</label><select id="bk-l"><option value="s">Короткие — до подбородка</option><option value="m" selected>Средние — до плеч</option><option value="l">Длинные — ниже лопаток</option></select></div>
<div class="row2"><div class="fld"><label for="bk-d">Желаемая дата</label><input id="bk-d" type="date"></div><div class="fld"><label for="bk-t">Время</label><select id="bk-t"><option>Утро</option><option selected>День</option><option>Вечер</option><option>Любое</option></select></div></div>
<div class="row2"><div class="fld"><label for="bk-n">Имя</label><input id="bk-n" autocomplete="name" placeholder="Как к вам обращаться"></div><div class="fld"><label for="bk-p">Телефон</label><input id="bk-p" type="tel" autocomplete="tel" placeholder="+7"></div></div>
<div class="fld"><label for="bk-c">Комментарий</label><textarea id="bk-c" placeholder="Например: хочу светлее на 2 тона"></textarea></div>
<div class="sum glass"><span>Ориентировочно</span><b id="bk-sum"></b></div>
<div class="sendrow"><button class="btn gold" data-send="wa">WhatsApp</button><button class="btn ghost" data-send="tg">Telegram</button><a class="btn ghost wide" href="${esc(booking)}" target="_blank" rel="noopener">Онлайн-запись Яндекс</a></div>
<p class="hint">Заявка откроется в мессенджере уже с текстом — останется нажать «Отправить». Мастер подтвердит время.</p></div></div>`);
        m = $("#book");
        const upd = () => {
          const s = svcs.find((x) => x.id === $("#bk-s").value) || {};
          $("#bk-lw").style.display = isObj(s.price) ? "" : "none";
          $("#bk-sum").textContent = s.price != null ? priceLabel(s.price, isObj(s.price) ? $("#bk-l").value : "") : "";
        };
        m.addEventListener("change", upd);
        m.addEventListener("click", (e) => {
          if (e.target === m || e.target.closest("[data-close]")) return m.classList.remove("on");
          const b = e.target.closest("[data-send]"); if (!b) return;
          const s = svcs.find((x) => x.id === $("#bk-s").value) || {};
          if (!$("#bk-n").value.trim() || !$("#bk-p").value.trim()) { toast("Укажите имя и телефон"); return; }
          const d = $("#bk-d").value;
          const txt = `Здравствуйте, Анастасия! Хочу записаться.\nУслуга: ${s.name}${isObj(s.price) ? ` (${LEN[$("#bk-l").value]} волосы)` : ""}\nЖелаемая дата: ${d ? dateRu(d) : "любая"}, ${$("#bk-t").value.toLowerCase()}\nИмя: ${$("#bk-n").value.trim()}\nТелефон: ${$("#bk-p").value.trim()}${$("#bk-c").value.trim() ? "\nКомментарий: " + $("#bk-c").value.trim() : ""}`;
          if (b.dataset.send === "wa") window.open("https://wa.me/" + String(P.whatsapp).replace(/\D/g, "") + "?text=" + encodeURIComponent(txt), "_blank", "noopener");
          else {
            // Telegram не принимает готовый текст в ссылке на номер: копируем заявку и открываем чат
            const go = () => window.open(P.telegram, "_blank", "noopener");
            if (navigator.clipboard) navigator.clipboard.writeText(txt).then(() => { toast("Текст заявки скопирован — вставьте в чат"); go(); }, go);
            else go();
          }
        });
        addEventListener("keydown", (e) => e.key === "Escape" && m.classList.remove("on"));
        const dt = $("#bk-d"); dt.min = new Date().toISOString().slice(0, 10);
      }
      if (sid) $("#bk-s").value = sid;
      m.dispatchEvent(new Event("change"));
      m.classList.add("on");
      $("#mmenu").classList.remove("on"); document.body.style.overflow = "";
      setTimeout(() => $("#bk-s").focus(), 50);
    }

    function initReveal() {
      if (RM || !("IntersectionObserver" in window)) return;
      const io = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) { e.target.classList.remove("pre"); io.unobserve(e.target); } }), { rootMargin: "0px 0px -8% 0px" });
      $$(".rv").forEach((el) => { if (el.getBoundingClientRect().top > innerHeight) { el.classList.add("pre"); io.observe(el); } });
    }

    function jsonLd() {
      const s = document.createElement("script");
      s.type = "application/ld+json";
      s.textContent = JSON.stringify({
        "@context": "https://schema.org", "@type": "HairSalon", name: P.name + " — " + P.title,
        telephone: P.phone, address: { "@type": "PostalAddress", streetAddress: "ул. Аксакова, 81", addressLocality: P.city, addressCountry: "RU" },
        aggregateRating: { "@type": "AggregateRating", ratingValue: String(P.rating).replace(",", "."), ratingCount: P.ratingCount },
        makesOffer: (D.services || []).filter((x) => !x.hidden).map((x) => ({ "@type": "Offer", name: x.name, price: priceFrom(x.price), priceCurrency: "RUB" })),
      });
      document.head.appendChild(s);
    }

    function initShader() {
(function(){
  const cv = document.getElementById("shader");
  const gl = cv.getContext("webgl", { antialias:false, premultipliedAlpha:false, powerPreference:"low-power" });
  if (!gl) return;
  const vs = "attribute vec2 p;void main(){gl_Position=vec4(p,0.,1.);}";
  const fs = `precision mediump float;
uniform vec2 r;uniform float t;
vec3 mod289(vec3 x){return x-floor(x*(1./289.))*289.;}vec4 mod289(vec4 x){return x-floor(x*(1./289.))*289.;}
vec4 permute(vec4 x){return mod289(((x*34.)+1.)*x);}vec4 tis(vec4 r){return 1.79284291400159-.85373472095314*r;}
vec3 fade(vec3 t){return t*t*t*(t*(t*6.-15.)+10.);}
float cnoise(vec3 P){vec3 Pi0=floor(P),Pi1=Pi0+1.;Pi0=mod289(Pi0);Pi1=mod289(Pi1);vec3 Pf0=fract(P),Pf1=Pf0-1.;
vec4 ix=vec4(Pi0.x,Pi1.x,Pi0.x,Pi1.x),iy=vec4(Pi0.yy,Pi1.yy),iz0=Pi0.zzzz,iz1=Pi1.zzzz;
vec4 ixy=permute(permute(ix)+iy),ixy0=permute(ixy+iz0),ixy1=permute(ixy+iz1);
vec4 gx0=ixy0*(1./7.),gy0=fract(floor(gx0)*(1./7.))-.5;gx0=fract(gx0);vec4 gz0=.5-abs(gx0)-abs(gy0),sz0=step(gz0,vec4(0.));gx0-=sz0*(step(0.,gx0)-.5);gy0-=sz0*(step(0.,gy0)-.5);
vec4 gx1=ixy1*(1./7.),gy1=fract(floor(gx1)*(1./7.))-.5;gx1=fract(gx1);vec4 gz1=.5-abs(gx1)-abs(gy1),sz1=step(gz1,vec4(0.));gx1-=sz1*(step(0.,gx1)-.5);gy1-=sz1*(step(0.,gy1)-.5);
vec3 g000=vec3(gx0.x,gy0.x,gz0.x),g100=vec3(gx0.y,gy0.y,gz0.y),g010=vec3(gx0.z,gy0.z,gz0.z),g110=vec3(gx0.w,gy0.w,gz0.w),g001=vec3(gx1.x,gy1.x,gz1.x),g101=vec3(gx1.y,gy1.y,gz1.y),g011=vec3(gx1.z,gy1.z,gz1.z),g111=vec3(gx1.w,gy1.w,gz1.w);
vec4 n0=tis(vec4(dot(g000,g000),dot(g010,g010),dot(g100,g100),dot(g110,g110)));g000*=n0.x;g010*=n0.y;g100*=n0.z;g110*=n0.w;
vec4 n1=tis(vec4(dot(g001,g001),dot(g011,g011),dot(g101,g101),dot(g111,g111)));g001*=n1.x;g011*=n1.y;g101*=n1.z;g111*=n1.w;
float a=dot(g000,Pf0),b=dot(g100,vec3(Pf1.x,Pf0.yz)),c=dot(g010,vec3(Pf0.x,Pf1.y,Pf0.z)),d=dot(g110,vec3(Pf1.xy,Pf0.z)),e=dot(g001,vec3(Pf0.xy,Pf1.z)),f=dot(g101,vec3(Pf1.x,Pf0.y,Pf1.z)),g=dot(g011,vec3(Pf0.x,Pf1.yz)),h=dot(g111,Pf1);
vec3 fx=fade(Pf0);vec4 nz=mix(vec4(a,b,c,d),vec4(e,f,g,h),fx.z);vec2 nyz=mix(nz.xy,nz.zw,fx.y);return 2.2*mix(nyz.x,nyz.y,fx.x);}
void main(){vec2 uv=gl_FragCoord.xy/r;vec2 p=uv*vec2(r.x/r.y,1.);
float n=cnoise(vec3(p*1.25+vec2(0.,t*.05),t*.08));
float s=sin((p.x*2.3-p.y*3.1)+n*2.4+t*.25)*.5+.5;   /* «пряди»: вытянутые волны по диагонали */
float k=smoothstep(.0,1.,uv.y*.9+n*.35);
vec3 c1=vec3(.07,.05,.04),c2=vec3(.42,.27,.16),c3=vec3(.86,.70,.49);
vec3 col=mix(c1,c2,k);col=mix(col,c3,smoothstep(.55,1.,s)*k*.85);
col+=.06*sin(vec3(0.,.6,1.2)+n*3.+t*.2)*k;   /* лёгкий перелив */
gl_FragColor=vec4(col,1.);}`;
  const sh = (ty, src) => { const s = gl.createShader(ty); gl.shaderSource(s, src); gl.compileShader(s); return gl.getShaderParameter(s, gl.COMPILE_STATUS) ? s : null; };
  const v = sh(gl.VERTEX_SHADER, vs), f = sh(gl.FRAGMENT_SHADER, fs);
  if (!v || !f) return;
  const pr = gl.createProgram(); gl.attachShader(pr, v); gl.attachShader(pr, f); gl.linkProgram(pr); gl.useProgram(pr);
  gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1,3,-1,-1,3]), gl.STATIC_DRAW);
  const loc = gl.getAttribLocation(pr, "p"); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
  const ur = gl.getUniformLocation(pr, "r"), ut = gl.getUniformLocation(pr, "t");
  // половинное разрешение: градиент мягкий, а батарея телефона важнее
  const size = () => { const k = Math.min(1, devicePixelRatio || 1) * .5; cv.width = Math.max(2, cv.clientWidth * k | 0); cv.height = Math.max(2, cv.clientHeight * k | 0); gl.viewport(0, 0, cv.width, cv.height); };
  size(); addEventListener("resize", size);
  let vis = true, t0 = performance.now();
  new IntersectionObserver((e) => { vis = e[0].isIntersecting; if (vis) raf(); }).observe(cv);
  let on = false;
  function draw(ts){ on = false; gl.uniform2f(ur, cv.width, cv.height); gl.uniform1f(ut, RM ? 8 : (ts - t0) / 1000 + 8); gl.drawArrays(gl.TRIANGLES, 0, 3); if (vis && !RM && !document.hidden) raf(); }
  function raf(){ if (!on) { on = true; requestAnimationFrame(draw); } }
  document.addEventListener("visibilitychange", raf);
  raf();
})();


    }
  });

})();
