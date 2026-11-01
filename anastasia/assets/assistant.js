/* Помощник на сайте: подбор услуги, цены по длине, как добраться, уход, запись.
   Работает в браузере по правилам на данных сайта (data.js) — без сервера и платных ключей. */
(function () {
  "use strict";
  function start() {
    const S = window.SITE; if (!S || document.getElementById("ai")) return;
    const D = S.D, P = D.profile || {}, A = D.assistant || {};
    if (A.on === false) return;
    const svcs = (D.services || []).filter((s) => !s.hidden);
    const esc = (v) => String(v == null ? "" : v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    const norm = (t) => String(t).toLowerCase().replace(/ё/g, "е").replace(/[^a-zа-я0-9\s]/g, " ").replace(/\s+/g, " ").trim();
    const LEN = { s: "короткие", m: "средние", l: "длинные" };
    let len = sessionStorage.getItem("ai_len") || "";

    document.body.insertAdjacentHTML("beforeend", `
<button class="ai-fab glass lens" id="ai-fab" aria-label="Открыть помощника" aria-expanded="false"><span class="ai-dot"></span><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="M12 3l1.8 4.6L18 9l-4.2 1.6L12 15l-1.8-4.4L6 9l4.2-1.4z"/><path d="M18.5 15.5l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z"/></svg><span class="ai-lbl">Помощник</span></button>
<section class="ai glass" id="ai" role="dialog" aria-label="Помощник по записи" aria-hidden="true">
  <header class="ai-h"><div class="ai-av" aria-hidden="true">АГ</div><div><b>Помощник Анастасии</b><small><i></i>отвечает сразу</small></div><button class="ai-x" aria-label="Закрыть">✕</button></header>
  <div class="ai-log" id="ai-log" aria-live="polite"></div>
  <div class="ai-chips" id="ai-chips"></div>
  <form class="ai-in" id="ai-form" autocomplete="off"><input id="ai-q" placeholder="Спросите про цену, запись, адрес…" aria-label="Ваш вопрос" enterkeyhint="send"><button aria-label="Отправить"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M4 12l16-8-6 16-2-7z"/></svg></button></form>
</section>`);
    const box = document.getElementById("ai"), log = document.getElementById("ai-log"), chips = document.getElementById("ai-chips"), fab = document.getElementById("ai-fab");

    const open = (v) => {
      box.classList.toggle("on", v); fab.classList.toggle("hide", v);
      box.setAttribute("aria-hidden", !v); fab.setAttribute("aria-expanded", v);
      if (v) { const dot = fab.querySelector(".ai-dot"); if (dot) dot.remove(); if (!log.children.length) hello(); setTimeout(() => matchMedia("(pointer:fine)").matches && document.getElementById("ai-q").focus(), 200); }
    };
    fab.onclick = () => open(true);
    box.querySelector(".ai-x").onclick = () => open(false);
    addEventListener("keydown", (e) => e.key === "Escape" && box.classList.contains("on") && open(false));
    // приглашение через 25 с, один раз за визит
    if (!sessionStorage.getItem("ai_peek")) setTimeout(() => { if (!box.classList.contains("on")) { fab.classList.add("peek"); sessionStorage.setItem("ai_peek", "1"); setTimeout(() => fab.classList.remove("peek"), 6000); } }, 25000);

    function say(html, who = "bot") {
      const d = document.createElement("div"); d.className = "ai-m " + who;
      if (who === "bot") { d.innerHTML = '<span class="ai-typing"><i></i><i></i><i></i></span>'; log.appendChild(d); setTimeout(() => { d.innerHTML = html; log.scrollTop = log.scrollHeight; }, 380); }
      else { d.textContent = html; log.appendChild(d); }
      log.scrollTop = log.scrollHeight;
    }
    const setChips = (L) => (chips.innerHTML = L.map(([t, a]) => `<button data-a="${esc(a)}">${esc(t)}</button>`).join(""));
    const MAIN = [["✨ Подобрать окрашивание", "quiz"], ["💰 Цены", "prices"], ["📅 Записаться", "book"], ["📍 Как добраться", "where"], ["🌿 Уход после окрашивания", "care"], ["💬 Написать мастеру", "human"]];
    const priceTxt = (s) => (S.isObj(s.price) && len ? S.fmt(s.price[len]) + ` <span class="ai-sub">(${LEN[len]} волосы)</span>` : S.priceLabel(s.price));
    const bookBtn = (sid, note, t = "Записаться") => `<button class="ai-cta" data-book-ai="${esc(sid || "")}" data-note="${esc(note || "")}">${t}</button>`;

    function hello() {
      const h = new Date().getHours();
      const g = h < 6 ? "Доброй ночи" : h < 12 ? "Доброе утро" : h < 18 ? "Добрый день" : "Добрый вечер";
      say(`${g}! ${esc(A.greeting || "Я помогу подобрать окрашивание, подскажу цену под вашу длину волос и запишу к Анастасии. С чего начнём?")}`);
      setChips(MAIN);
    }

    // ---------- подбор услуги (квиз) ----------
    const Q = { goal: "", len: "", last: "" };
    const GOALS = [["Освежить свой цвет", "fresh"], ["Стать блондинкой / светлее", "blonde"], ["Сложное окрашивание, Airtouch", "complex"], ["Светлые пряди у лица", "contour"], ["Закрасить корни / седину", "roots"], ["Восстановить волосы", "care"], ["Только стрижка", "cut"]];
    function quiz(step) {
      if (step === 1) { say("Что хочется получить в итоге?"); setChips(GOALS.map(([t, v]) => [t, "q1:" + v])); }
      if (step === 2) { say("Какая у вас длина волос?"); setChips([["До подбородка", "q2:s"], ["До плеч", "q2:m"], ["Ниже лопаток", "q2:l"]]); }
      if (step === 3) { say("Когда последний раз окрашивались?"); setChips([["Не окрашиваюсь", "q3:none"], ["Меньше 2 месяцев назад", "q3:recent"], ["Давно", "q3:old"], ["Были чёрные / тёмные краски", "q3:dark"]]); }
      if (step === 4) result();
    }
    function result() {
      const pick = { fresh: "s3", blonde: "s1", complex: "s1", contour: "s4", roots: Q.last === "old" ? "s6" : "s5", care: "s12", cut: "s8" }[Q.goal];
      const s = svcs.find((x) => x.id === pick) || svcs[0];
      const extra = [];
      if (Q.goal === "blonde" && Q.last === "dark") extra.push("Выход из тёмного цвета — задача на несколько этапов. Лучше начать с консультации: Анастасия оценит волосы и честно скажет, какой результат реален за один визит.");
      if (["blonde", "complex"].includes(Q.goal)) extra.push("К осветлению стоит добавить уход Alfaparf Milano — волосы будут мягкими и блестящими.");
      if (Q.goal === "fresh") extra.push("Если хочется мягкого перехода от корней — посмотрите и растяжку цвета.");
      const alt = Q.goal === "fresh" ? svcs.find((x) => x.id === "s2") : ["blonde", "complex"].includes(Q.goal) ? svcs.find((x) => x.id === "s11" || x.id === "s12") : null;
      const consult = svcs.find((x) => x.id === "s15");
      say(`<div class="ai-card">${s.img ? `<img src="${esc(s.img)}" alt="">` : ""}<div><small>Рекомендую</small><b>${esc(s.name)}</b><span>${priceTxt(s)}</span></div></div>${s.desc ? `<p>${esc(s.desc)}</p>` : ""}${extra.map((t) => `<p>${esc(t)}</p>`).join("")}
${alt ? `<p class="ai-sub">Также подойдёт: ${esc(alt.name)} — ${priceTxt(alt)}</p>` : ""}${bookBtn(s.id, "Подбор помощника: " + GOALS.find((g) => g[1] === Q.goal)[0].toLowerCase())}${consult ? ` ${bookBtn(consult.id, "Хочу консультацию перед окрашиванием", "Сначала консультация · " + S.fmt(consult.price))}` : ""}`);
      setChips([["Пройти ещё раз", "quiz"], ["Все цены", "prices"], ["Как добраться", "where"]]);
    }

    // ---------- ответы ----------
    function prices() {
      const cats = D.categories || [];
      say(`${len ? "" : '<p class="ai-sub">Цена окрашивания зависит от длины — выберите её ниже, пересчитаю.</p>'}${cats.map((c) => { const L = svcs.filter((s) => s.cat === c.id); return L.length ? `<p><b>${esc(c.name)}</b></p><ul class="ai-list">${L.map((s) => `<li><span>${esc(s.name)}</span><b>${priceTxt(s)}</b></li>`).join("")}</ul>` : ""; }).join("")}<a class="ai-link" href="uslugi.html">Подробнее на странице услуг →</a>`);
      setChips([["До подбородка", "len:s"], ["До плеч", "len:m"], ["Ниже лопаток", "len:l"], ["📅 Записаться", "book"]]);
    }
    const where = () => { say(`<p><b>${esc(P.address)}</b><br>${esc(P.addressNote)}</p><p>${esc(P.hours)}</p><a class="ai-link" href="${esc(P.route)}" target="_blank" rel="noopener">Построить маршрут →</a>`); setChips(MAIN.filter((c) => c[1] !== "where")); };
    const care = () => { say(`<p>Чтобы цвет держался дольше:</p><ul class="ai-dots"><li>первые 2–3 дня после окрашивания не мойте голову;</li><li>шампунь без сульфатов и мягкая вода — меньше вымывания цвета;</li><li>маска для окрашенных волос 1–2 раза в неделю;</li><li>термозащита перед феном и утюжком;</li><li>блонду — фиолетовый шампунь раз в неделю против желтизны.</li></ul><p>Персональный уход Анастасия подберёт после процедуры.</p>`); setChips([["Уход в салоне — цена", "svc:s12"], ["📅 Записаться", "book"], ["Другие вопросы", "menu"]]); };
    const human = () => { say(`<p>Напишите Анастасии напрямую:</p><div class="ai-row">${P.whatsapp ? `<a class="ai-cta" href="https://wa.me/${esc(String(P.whatsapp).replace(/\D/g, ""))}?text=${encodeURIComponent("Здравствуйте, Анастасия! У меня вопрос: ")}" target="_blank" rel="noopener">WhatsApp</a>` : ""}${P.telegram ? `<a class="ai-cta ghost" href="${esc(P.telegram)}" target="_blank" rel="noopener">Telegram</a>` : ""}<a class="ai-cta ghost" href="${S.tel(P.phone)}">Позвонить</a></div>`); setChips(MAIN.filter((c) => c[1] !== "human")); };
    const book = (sid, note) => { open(false); S.openBooking(sid || "", len || "", note || ""); };

    // распознавание свободного вопроса
    const INT = [
      ["book", /запис|окошк|окно|свобод|когда можно|время есть|забронир/],
      ["where", /адрес|где (вы|наход)|как (добрат|найти|пройти|доехать)|подъезд|этаж|парков|метро|маршрут|аксаков/],
      ["hours", /врем|час(ы|ов)|до скольк|работает|график|выходн|сегодня|завтра/],
      ["care", /уход (после|дома)|ухажив|шампун|маск|желтизн|вымыва|сохран/],
      ["consult", /консульт|сомнева|не знаю|подойдет ли|посовет/],
      ["brand", /космет|краск|alfaparf|альфапарф|чем (крас|работ)/],
      ["duration", /долго|сколько (длит|времени|по времени)|часов займет/],
      ["human", /(живой|человек|мастер[ау]? напис|позвон|телефон|whatsapp|ватсап|телеграм|telegram)/],
      ["quiz", /подобр|что (выбрать|мне подойдет)|какое окраш|хочу (стать|быть)|посовету/],
      ["prices", /цен|стоим|сколько стоит|прайс|почем|руб|₽|дорого/],
      ["thanks", /спасибо|благодар|понятно|ок$|супер/],
      ["hi", /^(привет|здравств|добр(ый|ое|ой)|хай|hello)/],
    ];
    function findSvc(q) {
      const words = q.split(" ").filter((w) => w.length > 3);
      let best = null, sc = 0;
      for (const s of svcs) {
        const n = norm(s.name + " " + (s.tag || ""));
        let k = 0; for (const w of words) if (n.includes(w.slice(0, Math.max(4, w.length - 2)))) k++;
        if (/airtouch|эйртач|айртач/.test(q) && s.id === "s1") k += 3;
        if (/блонд|осветл|мелир|балаяж/.test(q) && s.id === "s1") k += 2;
        if (/тонир/.test(q) && s.id === "s3") k += 2;
        if (/корн/.test(q) && s.id === "s5") k += 2;
        if (/кончик|секущ/.test(q) && s.id === "s8") k += 2;
        if (k > sc) { sc = k; best = s; }
      }
      return sc ? best : null;
    }
    function answer(raw) {
      const q = norm(raw);
      const L = /коротк|подбород|каре/.test(q) ? "s" : /средн|плеч/.test(q) ? "m" : /длинн|лопат|ниже/.test(q) ? "l" : "";
      if (L) { len = L; sessionStorage.setItem("ai_len", L); }
      const s = findSvc(q);
      const it = (INT.find(([, re]) => re.test(q)) || [""])[0];
      if (s && (it === "prices" || it === "" || it === "book" || it === "quiz")) {
        say(`<div class="ai-card">${s.img ? `<img src="${esc(s.img)}" alt="">` : ""}<div><small>${esc(((D.categories || []).find((c) => c.id === s.cat) || {}).name || "")}</small><b>${esc(s.name)}</b><span>${priceTxt(s)}</span></div></div>${s.desc ? `<p>${esc(s.desc)}</p>` : ""}${S.isObj(s.price) && !len ? '<p class="ai-sub">Цена зависит от длины — подскажите вашу.</p>' : ""}${bookBtn(s.id)}`);
        return setChips(S.isObj(s.price) && !len ? [["До подбородка", "len:s"], ["До плеч", "len:m"], ["Ниже лопаток", "len:l"]] : MAIN);
      }
      switch (it) {
        case "book": say("Отлично! Открываю запись — выберите услугу и удобную дату, заявка уйдёт Анастасии в мессенджер."); return setTimeout(() => book(), 900);
        case "where": return where();
        case "hours": say(`<p>${esc(P.hours)}. Запись заранее — так точно найдётся удобное время.</p>${bookBtn("")}`); return setChips(MAIN);
        case "care": return care();
        case "consult": { const c = svcs.find((x) => x.id === "s15"); say(`<p>Если сомневаетесь — начните с консультации${c ? ` (${S.fmt(c.price)}, сумма идёт в аванс следующей услуги)` : ""}. Анастасия посмотрит волосы и предложит варианты.</p>${c ? bookBtn(c.id, "Консультация") : ""}`); return setChips(MAIN); }
        case "brand": say(`<p>Анастасия работает на профессиональных красителях и уходе ${esc(P.brand)}.</p>`); return setChips(MAIN);
        case "duration": say("<p>Время зависит от техники и длины: тонирование — пара часов, сложное окрашивание может занять большую часть дня. Точное время Анастасия скажет при записи.</p>"); return setChips(MAIN);
        case "human": return human();
        case "quiz": return quiz(1);
        case "prices": return prices();
        case "thanks": say("Рада помочь! Если что-то ещё — спрашивайте 🙂"); return setChips(MAIN);
        case "hi": say("Здравствуйте! Чем помочь?"); return setChips(MAIN);
      }
      if (L) { say(`Запомнила: ${LEN[L]} волосы. Теперь цены буду показывать под вашу длину.`); return setChips(MAIN); }
      say(`<p>Не уверена, что поняла вопрос. Могу подобрать услугу, показать цены или передать вопрос Анастасии.</p>`);
      setChips(MAIN);
    }

    chips.addEventListener("click", (e) => {
      const b = e.target.closest("button"); if (!b) return;
      const a = b.dataset.a; say(b.textContent.replace(/^[^\wа-яё]+/i, "").trim(), "me");
      if (a === "quiz") return quiz(1);
      if (a === "menu") { say("Что ещё подсказать?"); return setChips(MAIN); }
      if (a.startsWith("q1:")) { Q.goal = a.slice(3); return Q.goal === "cut" || Q.goal === "care" ? (Q.last = "", len ? result() : quiz(2)) : quiz(2); }
      if (a.startsWith("q2:")) { Q.len = len = a.slice(3); sessionStorage.setItem("ai_len", len); return Q.goal === "cut" || Q.goal === "care" ? result() : quiz(3); }
      if (a.startsWith("q3:")) { Q.last = a.slice(3); return result(); }
      if (a.startsWith("len:")) { len = a.slice(4); sessionStorage.setItem("ai_len", len); return prices(); }
      if (a.startsWith("svc:")) return answer(svcs.find((s) => s.id === a.slice(4)).name);
      ({ prices, where, care, human, book: () => book() }[a] || (() => {}))();
    });
    log.addEventListener("click", (e) => { const b = e.target.closest("[data-book-ai]"); if (b) book(b.dataset.bookAi, b.dataset.note); });
    document.getElementById("ai-form").addEventListener("submit", (e) => { e.preventDefault(); const i = document.getElementById("ai-q"); const v = i.value.trim(); if (!v) return; say(v, "me"); i.value = ""; setTimeout(() => answer(v), 150); });
    window.openAssistant = (mode) => { open(true); if (mode === "quiz") { say("Подобрать окрашивание", "me"); quiz(1); } };
  }
  if (window.SITE) start(); else addEventListener("site:ready", start);
})();
