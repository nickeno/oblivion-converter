(() => {
  'use strict';
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const wait = ms => new Promise(r => setTimeout(r, reduce ? 0 : ms));
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const OUT = 'cubic-bezier(.22,1,.36,1)';
  const MOVE = 'cubic-bezier(.65,0,.35,1)';
  const GAME = { og: 'the original Oblivion', rem: 'Oblivion Remastered' };
  const STORE = { xbox: 'Game Pass', steam: 'Steam' };
  const other = g => (g === 'og' ? 'rem' : 'og');
  const norm = n => n.trim().toLowerCase();
  const plural = n => `${n} save${n === 1 ? '' : 's'}`;
  const CHEV = '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>';
  const SHADOW_UP = '0 22px 50px rgba(0,0,0,.5)';
  const SHADOW_DOWN = '0 0 0 rgba(0,0,0,0)';

  // ------------------------------------------------------------ the converter behind the window
  // In the app this is pywebview's bridge. With ?dev in the address it is the small test server.
  const DEV = new URLSearchParams(location.search).has('dev');
  const bridge = DEV ? Promise.resolve() : new Promise(res => {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.load) res();
    else addEventListener('pywebviewready', () => res(), { once: true });
  });
  async function call(name, ...args) {
    await bridge;
    if (!DEV) return window.pywebview.api[name](...args);
    const r = await fetch('/api/' + name, {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-OSC': '1' }, body: JSON.stringify(args),
    });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return r.json();
  }

  // ------------------------------------------------------------ data
  const groups = { og: [], rem: [] };
  const state = { group: { og: null, rem: null }, sel: null, busy: false, loaded: false, status: null };
  const lists = { og: $('#list-og'), rem: $('#list-rem') };
  const panels = { og: $('.panel[data-game="og"]'), rem: $('.panel[data-game="rem"]') };
  const go = $('#go');
  const sig = list => list.map(g => g.key + '=' + g.saves.map(s => s.id + '@' + s.saved_at).join(',')).join('|');
  const mixed = () => new Set(groups.rem.map(g => g.store)).size > 1;

  // start on the character that exists in both games, most recently played
  function startPick() {
    let best = null;
    for (const g of groups.og) {
      const twin = groups.rem.find(r => norm(r.name) === norm(g.name));
      if (!twin) continue;
      const t = Math.max(g.saves[0].saved_at, twin.saves[0].saved_at);
      if (!best || t > best.t) best = { og: g, rem: twin, t };
    }
    return best ? { og: best.og, rem: best.rem } : { og: groups.og[0] || null, rem: groups.rem[0] || null };
  }

  function when(ts) {
    if (!ts) return '';
    const d = Date.now() / 1000 - ts;
    if (d >= 0 && d < 60) return 'Just now';
    if (d >= 0 && d < 3600) return `${Math.floor(d / 60)} min ago`;
    const dt = new Date(ts * 1000), now = new Date();
    const time = dt.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
    if (dt.toDateString() === now.toDateString()) return `Today ${time}`;
    const y = new Date(); y.setDate(y.getDate() - 1);
    if (dt.toDateString() === y.toDateString()) return `Yesterday ${time}`;
    return dt.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: dt.getFullYear() === now.getFullYear() ? undefined : 'numeric' });
  }

  // ------------------------------------------------------------ save pictures, fetched as rows scroll into view
  const pics = new Map(), waiting = new Map(), queue = [];
  let active = 0;
  const pkey = s => s.id + '@' + s.saved_at;
  function pic(s) {
    const k = pkey(s);
    if (pics.has(k)) return Promise.resolve(pics.get(k));
    if (waiting.has(k)) return waiting.get(k);
    const p = new Promise(res => queue.push({ s, k, res }));
    waiting.set(k, p);
    pump();
    return p;
  }
  function pump() {
    while (active < 4 && queue.length) {
      const j = queue.pop();                       // newest request first: what is on screen right now
      active++;
      call('thumb', j.s.id).catch(() => null).then(u => {
        pics.set(j.k, u || null); waiting.delete(j.k); active--;
        j.res(u || null);
        pump();
      });
    }
  }
  function showPic(row) {
    pic(row._save).then(u => { if (u) { const img = $('.thumb img', row); img.src = u; img.classList.add('in'); } });
  }
  const seen = {};
  for (const g of ['og', 'rem']) {
    seen[g] = new IntersectionObserver(es => {
      for (const e of es) if (e.isIntersecting) { seen[g].unobserve(e.target); showPic(e.target); }
    }, { root: lists[g], rootMargin: '320px 0px' });
  }

  // ------------------------------------------------------------ text that rolls when it changes
  function roll(el, txt, animate = true) {
    const old = el.querySelector('span:last-child');
    if (old && old.textContent === txt) return;
    const s = document.createElement('span');
    s.textContent = txt;
    if (!old || !animate || reduce) { el.replaceChildren(s); return; }
    el.appendChild(s);
    old.animate([{ transform: 'translateY(0)', opacity: 1 }, { transform: 'translateY(-100%)', opacity: 0 }], { duration: 320, easing: OUT, fill: 'forwards' })
      .finished.then(() => old.remove());
    s.animate([{ transform: 'translateY(100%)', opacity: 0 }, { transform: 'translateY(0)', opacity: 1 }], { duration: 380, easing: OUT });
  }
  const goText = (t, animate = true) => roll($('#go-l'), t, animate);

  // ------------------------------------------------------------ a short message at the bottom
  const noteEl = $('#note');
  let noteT = 0;
  function say(text, bad) {
    noteEl.textContent = text;
    noteEl.classList.toggle('bad', !!bad);
    noteEl.hidden = false;
    noteEl.classList.add('off');
    void noteEl.offsetWidth;
    noteEl.classList.remove('off');
    clearTimeout(noteT);
    noteT = setTimeout(hush, bad ? 10000 : 6500);
  }
  function hush() { clearTimeout(noteT); noteEl.classList.add('off'); }
  noteEl.addEventListener('click', hush);

  // ------------------------------------------------------------ lists
  function rowEl(s, game) {
    const b = document.createElement('button');
    b.className = 'row';
    b.setAttribute('role', 'option');
    const u = pics.get(pkey(s)), w = when(s.saved_at);
    b.innerHTML = `<div class="thumb"><img alt=""${u ? ` class="in" src="${u}"` : ''}></div>
      <div><div class="t">${esc(s.location || 'Cyrodiil')}</div><div class="m">${esc(s.title)}<span class="m-lv">, level ${s.level}</span><span class="m-when">${w ? ', ' + w : ''}</span></div></div>
      <div class="when">${w}</div>`;
    b._save = s;
    b._game = game;
    s.el = b;
    if (!u) seen[game].observe(b);
    return b;
  }
  function emptyText(game) {
    const st = state.status;
    if (!state.loaded) return ['Looking for saves…', ''];
    if (game === 'og') {
      return st && !st.og_found
        ? ["Oblivion's save folder wasn't found", 'Play the original game and save once.']
        : ['No saves here yet', 'Save in the original game and it shows up here.'];
    }
    return st && !st.xbox_found && !st.steam_found
      ? ["Oblivion Remastered's saves weren't found", 'Play Remastered and save once.']
      : ['No saves here yet', 'Save once in Remastered and it shows up here.'];
  }
  function setHead(game, animate) {
    const g = state.group[game], who = $(`.who[data-game="${game}"]`);
    who.hidden = !g;
    if (!g) { roll($(`#count-${game}`), '', false); return; }
    const solo = groups[game].length < 2;
    const store = game === 'rem' && mixed() ? ` · ${STORE[g.store] || ''}` : '';
    who.classList.toggle('solo', solo);
    who.innerHTML = `${esc(g.name)} <span class="lvl">Level ${g.saves[0].level}${store}</span>${solo ? '' : CHEV}`;
    roll($(`#count-${game}`), plural(g.saves.length), animate);
  }
  function renderList(game, keepScroll) {
    const L = lists[game], g = state.group[game], top = L.scrollTop;
    seen[game].disconnect();
    L.innerHTML = '<span class="hl" aria-hidden="true"></span><div class="rows"></div>';
    const rows = $('.rows', L);
    if (!g) {
      const [a, b] = emptyText(game);
      rows.innerHTML = `<div class="empty">${esc(a)}<small>${esc(b)}</small></div>`;
    } else {
      const f = document.createDocumentFragment();
      g.saves.forEach(s => f.appendChild(rowEl(s, game)));
      rows.appendChild(f);
    }
    L.scrollTop = keepScroll ? top : 0;
    setHead(game, false);
    placeHl(game, true);
  }
  async function swapList(game) {
    const rows = $('.rows', lists[game]);
    rows.classList.add('out');
    await wait(180);
    renderList(game);
    const fresh = $('.rows', lists[game]);
    fresh.classList.add('out');
    requestAnimationFrame(() => fresh.classList.remove('out'));
  }

  // ------------------------------------------------------------ selection
  function placeHl(game, instant) {
    const L = lists[game], hl = $('.hl', L);
    if (!hl) return;
    const s = state.sel && state.sel.game === game ? state.sel.save : null;
    const row = s && s.el && L.contains(s.el) ? s.el : null;
    if (!row) { hl.style.opacity = '0'; return; }
    const hidden = hl.style.opacity !== '1';
    if (instant || hidden) hl.style.transition = 'none';
    hl.style.transform = `translateY(${row.offsetTop}px)`;
    if (instant || hidden) { void hl.offsetWidth; hl.style.transition = ''; }
    hl.style.opacity = '1';
  }
  function select(game, s, instant) {
    if (!s) return;
    state.sel = { game, save: s };
    for (const g of ['og', 'rem']) {
      $$('.row', lists[g]).forEach(r => r.classList.toggle('sel', r._save === s));
      placeHl(g, instant);
    }
    go.classList.toggle('left', game === 'rem');
    go.setAttribute('aria-label', `Convert this save to ${GAME[other(game)]}`);
  }

  // ------------------------------------------------------------ loading the saves
  function apply(d) {
    const first = !state.loaded;
    state.loaded = true;
    state.status = d.status;
    const sel = state.sel && { game: state.sel.game, id: state.sel.save.id };
    let changed = first;
    for (const game of ['og', 'rem']) {
      if (!first && sig(d[game]) === sig(groups[game])) continue;
      changed = true;
      const key = state.group[game] && state.group[game].key;
      groups[game] = d[game];
      if (!first) {
        state.group[game] = groups[game].find(g => g.key === key) || groups[game][0] || null;
        renderList(game, true);
      }
    }
    if (first) { state.group = startPick(); renderList('og'); renderList('rem'); }
    if (!changed) return;
    // the same save stays picked when it is still there
    let game = sel && sel.game, s = sel && state.group[game] && state.group[game].saves.find(x => x.id === sel.id);
    if (!s) {
      state.sel = null;
      for (const g of [game || 'og', 'og', 'rem']) {
        if (state.group[g] && state.group[g].saves[0]) { game = g; s = state.group[g].saves[0]; break; }
      }
    }
    if (s) select(game, s, true);
    else { placeHl('og', true); placeHl('rem', true); }
    setHead('og', false); setHead('rem', false);
  }
  let loading = false;
  async function refresh() {
    if (loading || state.busy || drag) return;
    loading = true;
    try {
      const d = await call('load');
      if (d && d.ok && !state.busy && !drag) apply(d);
      else if (d && !d.ok && !state.loaded) say(d.error, true);
    } catch (e) {
      if (!state.loaded) say("The converter didn't start. Close the app and open it again.", true);
    } finally { loading = false; }
  }

  // ------------------------------------------------------------ character menu
  const menu = $('#menu');
  let menuBtn = null;
  function openMenu(btn) {
    const game = btn.dataset.game;
    menu.innerHTML = '';
    groups[game].forEach(g => {
      const b = document.createElement('button');
      b.setAttribute('role', 'menuitem');
      if (g === state.group[game]) b.className = 'on';
      const store = game === 'rem' && mixed() ? ` · ${STORE[g.store] || ''}` : '';
      b.innerHTML = `<span>${esc(g.name)}</span><small>Level ${g.saves[0].level} · ${plural(g.saves.length)}${store}</small>`;
      b.addEventListener('click', () => { closeMenu(); pickGroup(game, g); });
      menu.appendChild(b);
    });
    menu.hidden = false;
    const r = btn.getBoundingClientRect();
    const left = Math.min(r.left, innerWidth - menu.offsetWidth - 12);
    menu.style.left = Math.max(12, left) + 'px';
    menu.style.top = r.bottom + 8 + 'px';
    btn.setAttribute('aria-expanded', 'true');
    menuBtn = btn;
    menu.animate([{ opacity: 0, transform: 'translateY(-6px) scale(.97)' }, { opacity: 1, transform: 'none' }], { duration: reduce ? 1 : 200, easing: OUT });
  }
  function closeMenu() {
    if (menu.hidden) return;
    menuBtn && menuBtn.setAttribute('aria-expanded', 'false');
    menuBtn = null;
    menu.animate([{ opacity: 1 }, { opacity: 0, transform: 'translateY(-4px) scale(.98)' }], { duration: reduce ? 1 : 130, easing: 'ease-in' })
      .finished.then(() => { if (!menuBtn) menu.hidden = true; });
  }
  async function pickGroup(game, g) {
    if (g === state.group[game] || state.busy) return;
    state.group[game] = g;
    const hadSel = state.sel && state.sel.game === game;
    await swapList(game);
    if (hadSel) select(game, g.saves[0], true);
  }

  // ------------------------------------------------------------ carrying a save across
  function makeCarry(row) {
    const r = row.getBoundingClientRect();
    const c = row.cloneNode(true);
    c.classList.remove('sel', 'fresh', 'dragging');
    c.classList.add('carry');
    c.removeAttribute('role');
    Object.assign(c.style, { width: r.width + 'px', height: r.height + 'px', transform: `translate(${r.left}px, ${r.top}px)` });
    c._x = r.left; c._y = r.top; c._s = 1; c._rot = 0;
    c._home = { x: r.left, y: r.top };
    document.body.appendChild(c);
    return c;
  }
  const tf = (x, y, s = 1, rot = 0) => `translate(${x}px, ${y}px) rotate(${rot}deg) scale(${s})`;
  function lift(c) {
    c._s = 1.03;
    return c.animate([{ transform: tf(c._x, c._y, 1), boxShadow: SHADOW_DOWN }, { transform: tf(c._x, c._y, 1.03), boxShadow: SHADOW_UP }],
      { duration: reduce ? 1 : 200, easing: OUT, fill: 'forwards' }).finished;
  }
  // a gentle curve, sampled so the timing curve stays smooth along the whole path
  function carryTo(c, x, y, dir) {
    const x0 = c._x, y0 = c._y, s0 = c._s, r0 = c._rot;
    const cx = (x0 + x) / 2, cy = Math.min(y0, y) - (Math.abs(x - x0) > 40 ? 34 : 0);
    const cxs = Math.abs(x - x0) > 40 ? cx : Math.max(x0, x) + 30;
    const frames = [];
    for (let i = 0; i <= 16; i++) {
      const t = i / 16, u = 1 - t;
      const px = u * u * x0 + 2 * u * t * cxs + t * t * x;
      const py = u * u * y0 + 2 * u * t * (Math.abs(x - x0) > 40 ? cy : (y0 + y) / 2) + t * t * y;
      const rot = r0 * u + Math.sin(t * Math.PI) * 1.4 * dir;
      frames.push({ transform: tf(px, py, s0 + Math.sin(t * Math.PI) * .01, rot), boxShadow: SHADOW_UP });
    }
    c._x = x; c._y = y; c._rot = 0;
    return c.animate(frames, { duration: reduce ? 1 : 720, easing: MOVE, fill: 'forwards' }).finished;
  }
  // through the gate: the save is drawn into the fire, then comes out the other side
  const HOT = 'sepia(1) saturate(5) hue-rotate(-28deg) brightness(1.15)';
  function intoGate(c, gx, gy) {
    const w = c.offsetWidth, h = c.offsetHeight, x0 = c._x, y0 = c._y, s0 = c._s;
    const x = gx - w / 2, y = gy - h / 2, frames = [];
    for (let i = 0; i <= 12; i++) {
      const t = i / 12, e = t * t * t;                       // speeds up as the gate pulls it in
      const px = x0 + (x - x0) * (1 - (1 - t) * (1 - t)), py = y0 + (y - y0) * t * t;
      frames.push({ transform: tf(px, py, s0 + (.08 - s0) * e, (x - x0 > 0 ? 1 : -1) * 10 * e), filter: t < .45 ? 'none' : HOT,
        opacity: 1 - Math.max(0, t - .7) / .3, boxShadow: SHADOW_UP, offset: t });
    }
    c._x = x; c._y = y; c._s = .08;
    return c.animate(frames, { duration: reduce ? 1 : 620, easing: 'linear', fill: 'forwards' }).finished;
  }
  function outOfGate(c, x, y) {
    const x0 = c._x, y0 = c._y, frames = [];
    for (let i = 0; i <= 12; i++) {
      const t = i / 12, e = 1 - Math.pow(1 - t, 3);
      const px = x0 + (x - x0) * e, py = y0 + (y - y0) * e - Math.sin(t * Math.PI) * 26;
      frames.push({ transform: tf(px, py, .08 + (1.03 - .08) * e, (x - x0 > 0 ? -6 : 6) * (1 - e)),
        filter: t < .5 ? HOT : 'none', opacity: Math.min(1, t / .18), boxShadow: SHADOW_UP, offset: t });
    }
    c._x = x; c._y = y; c._s = 1.03; c._rot = 0;
    return c.animate(frames, { duration: reduce ? 1 : 640, easing: 'linear', fill: 'forwards' }).finished;
  }
  function settle(c) {
    return c.animate([{ transform: tf(c._x, c._y, c._s), boxShadow: SHADOW_UP }, { transform: tf(c._x, c._y, 1), boxShadow: SHADOW_DOWN }],
      { duration: reduce ? 1 : 240, easing: OUT, fill: 'forwards' }).finished;
  }

  async function convert(carried) {
    if (state.busy) return;
    if (!state.sel) { say('Pick a save to convert first.'); return; }
    const { game: from, save: s } = state.sel;
    const to = other(from), row = s.el;
    state.busy = true;
    go.classList.add('working');
    hush();
    closeMenu();
    Fire.set({ heat: 1, gate: 1 });
    goText('Converting…');

    // the real work starts right away; the save waits inside the gate until it is done
    const target = to === 'rem' && state.group.rem ? state.group.rem.target : null;
    const job = call('convert', s.id, target).catch(() => ({ ok: false, error: "The converter didn't answer. Try again." }));
    const c = carried || makeCarry(row);
    if (!carried) await lift(c);
    const gr = go.getBoundingClientRect();
    await intoGate(c, gr.left + gr.width / 2, gr.top + gr.height / 2);
    Fire.set({ heat: 1.25 });
    const [res] = await Promise.all([job, wait(240)]);
    Fire.set({ heat: 1 });

    const tg = res && res.ok && res.data[to].find(g => g.saves.some(x => x.id === res.new_id));
    if (!tg) {
      // it did not work: the save comes back out where it was
      await outOfGate(c, c._home.x, c._home.y);
      await settle(c);
      c.remove();
      row.classList.remove('dragging');
      go.classList.remove('working');
      Fire.idle();
      goText('Convert');
      say((res && res.error) || "That save couldn't be converted.", true);
      state.busy = false;
      return;
    }

    // the other side shows the character the new save belongs to, with a gap where it will land
    groups[to] = res.data[to];
    const ns = tg.saves.find(x => x.id === res.new_id);
    const L = lists[to], count = $(`#count-${to}`);
    const swap = !state.group[to] || state.group[to].key !== tg.key;
    state.group[to] = tg;
    await Promise.race([pic(ns), wait(900)]);
    if (swap) { $('.rows', L).classList.add('out'); await wait(180); }
    renderList(to, !swap);
    roll(count, plural(tg.saves.length - 1), false);
    const nr = ns.el, slot = document.createElement('div'), h = nr.offsetHeight;
    slot.className = 'slot';
    nr.replaceWith(slot);
    slot.appendChild(nr);
    nr.style.opacity = '0';
    if (slot.offsetTop < L.scrollTop || slot.offsetTop + h > L.scrollTop + L.clientHeight) {
      L.scrollTop = Math.max(0, slot.offsetTop - (L.clientHeight - h) / 2);
    }
    if (swap) {
      const fresh = $('.rows', L);
      fresh.classList.add('out');
      requestAnimationFrame(() => fresh.classList.remove('out'));
    }
    slot.animate([{ height: '0px' }, { height: h + 'px' }], { duration: reduce ? 1 : 560, easing: OUT });

    // out of the gate and into the gap
    const lr = L.getBoundingClientRect();
    await outOfGate(c, lr.left, lr.top + slot.offsetTop - L.scrollTop);
    await settle(c);
    nr.style.opacity = '';
    nr.classList.add('fresh');
    c.remove();
    row.classList.remove('dragging');
    roll(count, plural(tg.saves.length), true);
    placeHl(from, true);

    go.classList.remove('working');
    Fire.idle();
    goText('Done');
    say(`${ns.title} is ready. Load it in ${GAME[to]}.`);
    await wait(1500);
    goText('Convert');
    state.busy = false;
  }

  // ------------------------------------------------------------ drag a save to the other side
  let drag = null;
  $('#panes').addEventListener('pointerdown', e => {
    const row = e.target.closest('.row');
    if (!row || row.classList.contains('carry') || state.busy || e.button !== 0) return;
    drag = { row, x0: e.clientX, y0: e.clientY, started: false, lastX: e.clientX, tilt: 0 };
  });
  addEventListener('pointermove', e => {
    if (!drag) return;
    const dx = e.clientX - drag.x0, dy = e.clientY - drag.y0;
    if (!drag.started) {
      if (Math.hypot(dx, dy) < 8) return;
      drag.started = true;
      select(drag.row._game, drag.row._save);
      drag.c = makeCarry(drag.row);
      drag.ox = drag.c._x; drag.oy = drag.c._y;
      drag.row.classList.add('dragging');
      lift(drag.c);
      document.body.style.cursor = 'grabbing';
    }
    const vx = e.clientX - drag.lastX;
    drag.lastX = e.clientX;
    drag.tilt += (Math.max(-4, Math.min(4, vx * .5)) - drag.tilt) * .25;
    const c = drag.c;
    c.getAnimations().forEach(a => a.cancel());
    c._x = drag.ox + dx; c._y = drag.oy + dy; c._s = 1.03; c._rot = drag.tilt;
    c.style.boxShadow = SHADOW_UP;
    c.style.transform = tf(c._x, c._y, 1.03, drag.tilt);
    const target = panels[other(drag.row._game)].getBoundingClientRect();
    drag.over = e.clientX > target.left && e.clientX < target.right && e.clientY > target.top && e.clientY < target.bottom;
    panels[other(drag.row._game)].classList.toggle('drop', drag.over);
  });
  addEventListener('pointerup', async () => {
    if (!drag) return;
    const d = drag;
    drag = null;
    document.body.style.cursor = '';
    if (!d.started) return;
    panels.og.classList.remove('drop');
    panels.rem.classList.remove('drop');
    if (d.over) {
      convert(d.c);
    } else {
      await carryTo(d.c, d.ox, d.oy, 0);
      await settle(d.c);
      d.c.remove();
      d.row.classList.remove('dragging');
    }
  });

  // ------------------------------------------------------------ events
  $('#panes').addEventListener('click', e => {
    const who = e.target.closest('.who');
    if (who) { e.stopPropagation(); menuBtn === who ? closeMenu() : (closeMenu(), openMenu(who)); return; }
    const row = e.target.closest('.row');
    if (row && !row.classList.contains('carry') && !state.busy) select(row._game, row._save);
  });
  document.addEventListener('click', e => { if (!menu.contains(e.target)) closeMenu(); });
  go.addEventListener('click', () => convert());
  go.addEventListener('pointerenter', () => { if (!state.busy) Fire.set({ heat: .6 }); });
  go.addEventListener('pointerleave', () => { if (!state.busy) Fire.set({ heat: .32 }); });
  go.addEventListener('pointerdown', () => { if (!state.busy) Fire.set({ heat: .9 }); });
  $('#b-backups').addEventListener('click', () => {
    call('open_backups').then(r => { if (r && !r.ok) say(r.error, true); }).catch(() => {});
  });
  addEventListener('keydown', e => {
    if (e.key === 'Escape') { closeMenu(); hush(); return; }
    if (!state.sel || state.busy || e.target.closest('.menu')) return;
    const list = $$('.row', lists[state.sel.game]);
    const i = list.findIndex(r => r._save === state.sel.save);
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const r = list[Math.max(0, Math.min(list.length - 1, i + (e.key === 'ArrowDown' ? 1 : -1)))];
      if (!r) return;
      select(r._game, r._save);
      r.scrollIntoView({ block: 'nearest', behavior: reduce ? 'auto' : 'smooth' });
    }
  });
  // the gate sign sits right behind the Convert button, its eye on the button
  function placeGate() {
    const gutter = $('#gutter'), narrow = innerWidth <= 860;
    // gate.png is 520x560; the sign in it is 321 wide and 454 tall, its middle at 260,284.
    // It gets clear room from both panels and from the top and bottom of the column.
    const fit = Math.min((gutter.offsetWidth - 88) / 321, ((gutter.offsetHeight - 112) / 2 - 28) / 227);
    const k = narrow ? .5 : Math.max(.45, Math.min(.8, fit));
    // Everything is worked out from the button's own box (whole pixels), never from where it is on screen:
    // a position read while the window is still sliding in, or before the label changes, would be off.
    const bw = go.offsetWidth, bh = go.offsetHeight, w = Math.round(520 * k), h = Math.round(560 * k);
    const left = Math.round(bw / 2 - w / 2), top = Math.round(bh / 2 - h * 284 / 560);
    for (const el of [$('#gate'), $('#fire')]) {
      Object.assign(el.style, { left: left + 'px', top: top + 'px', width: w + 'px', height: h + 'px' });
    }
    $('#gate').classList.add('on');
    Fire.place({ narrow, w, h, bx: bw / 2 - left, by: bh / 2 - top, bw, bh });
  }
  addEventListener('resize', () => { placeHl('og', true); placeHl('rem', true); closeMenu(); placeGate(); });
  new ResizeObserver(placeGate).observe($('#gutter'));
  new ResizeObserver(placeGate).observe(go);
  // saving in a game and coming back to this window shows the new save
  addEventListener('focus', refresh);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });

  // ------------------------------------------------------------ start
  renderList('og');
  renderList('rem');
  goText('Convert', false);
  placeGate();
  refresh();
})();
