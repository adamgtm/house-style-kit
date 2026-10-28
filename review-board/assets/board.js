/* Review board page. No dependencies. Data is embedded in #rb-data. */
(function () {
  'use strict';

  var DATA = JSON.parse(document.getElementById('rb-data').textContent);
  var TOKEN = (document.querySelector('meta[name=rb-token]') || {}).content || '';
  var SERVED = location.protocol === 'http:' && TOKEN && TOKEN !== '__RB_TOKEN__';
  var REV = DATA.revision;
  var KEY = 'rb:' + DATA.id + ':' + DATA.pathKey;
  var LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';

  /* ---------- small helpers ---------- */
  function h(tag, attrs, kids) {
    var el = document.createElement(tag);
    for (var k in (attrs || {})) {
      if (k === 'text') el.textContent = attrs[k];
      else if (attrs[k] !== false && attrs[k] != null) el.setAttribute(k, attrs[k] === true ? '' : attrs[k]);
    }
    (kids || []).forEach(function (c) { if (c) el.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return el;
  }
  function reduced() { return window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches; }
  function typing(t) { return !!t && (t.tagName === 'TEXTAREA' || t.tagName === 'INPUT' || t.tagName === 'SELECT' || t.isContentEditable); }
  function mod(e) { return e.metaKey || e.ctrlKey; }
  function say(msg) { var l = document.getElementById('live'); l.textContent = ''; setTimeout(function () { l.textContent = msg; }, 30); }
  function full(v) { return SERVED ? '/img/' + v.fp + '?v=' + REV : v.src; }
  function thumb(v) { return SERVED ? '/' + v.thumb + '?v=' + REV : v.thumb; }
  function ratio(v) { return v.w + ' / ' + v.h; }
  function grow(ta) { ta.style.height = 'auto'; ta.style.height = Math.max(ta.scrollHeight + 2, parseInt(getComputedStyle(ta).minHeight, 10) || 0) + 'px'; }
  function nowIso() { return new Date().toISOString().replace(/\.\d+Z$/, 'Z'); }
  function safeName(t) { return String(t).replace(/[^A-Za-z0-9._-]+/g, '-'); }
  function uid() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    return 's' + Date.now().toString(36) + Math.random().toString(36).slice(2, 10);
  }

  /* ---------- model and drafts ---------- */
  var items = [], byId = {};
  DATA.sections.forEach(function (s) {
    s.items.forEach(function (it) {
      it.section = s.name; it.sel = 0; it.dom = items.length; it.el = {};
      it.vById = {}; it.versions.forEach(function (v) { it.vById[v.id] = v; });
      items.push(it); byId[it.id] = it;
    });
  });

  var storageOk = true, skippedDrafts = 0;
  /* Read the stored drafts entry by entry: one corrupt entry is skipped, not the whole set.
     Only a real storage error (blocked, denied) marks storage as unavailable. */
  function readStore() {
    var out = {}, str = null;
    try { str = localStorage.getItem(KEY); } catch (e) { storageOk = false; return null; }
    var raw = {};
    if (str) { try { raw = JSON.parse(str) || {}; } catch (e) { skippedDrafts++; return out; } }
    var src = raw.items && typeof raw.items === 'object' ? raw.items : {};
    Object.keys(src).forEach(function (id) {
      try {
        var it = byId[id]; if (!it) return;
        var r = src[id];
        if (!r || typeof r !== 'object' || !Array.isArray(r.liked)) throw new Error('bad entry');
        out[id] = {
          liked: r.liked.filter(function (v) { return typeof v === 'string' && it.vById[v]; }),
          note: typeof r.note === 'string' ? r.note : ''
        };
      } catch (e) { skippedDrafts++; }
    });
    return out;
  }
  var drafts = readStore() || {};
  items.forEach(function (it) { if (!drafts[it.id]) drafts[it.id] = { liked: [], note: '' }; });
  var timer = null, dirty = {};  // dirty[id] = { liked: bool, note: bool }: what THIS tab changed since its last save
  /* Save field by field: re-read storage, then write only the fields this tab changed. A like-only
     change never rewrites the note, and an untouched note never overwrites another tab's. */
  function persist(id, field) {
    if (id) { dirty[id] = dirty[id] || {}; dirty[id][field] = true; }
    clearTimeout(timer);
    timer = setTimeout(function () {
      try {
        var raw = {}, cur = localStorage.getItem(KEY);
        if (cur) { try { raw = JSON.parse(cur) || {}; } catch (e) { raw = {}; } }
        if (!raw.items || typeof raw.items !== 'object') raw.items = {};
        Object.keys(dirty).forEach(function (k) {
          var e = raw.items[k];
          if (!e || typeof e !== 'object' || !Array.isArray(e.liked)) e = { liked: [], note: '' };
          if (dirty[k].liked) e.liked = drafts[k].liked.slice();
          if (dirty[k].note) e.note = drafts[k].note;
          raw.items[k] = e;
        });
        raw.saved = nowIso();
        localStorage.setItem(KEY, JSON.stringify(raw));
        dirty = {}; storageOk = true;
      } catch (e) { storageOk = false; }
      items.forEach(showSaved);
      if (FV.open) fvSync();
    }, 300);
  }
  /* Another tab saved: adopt each field this tab has not changed itself, even in a focused field. */
  window.addEventListener('storage', function (e) {
    if (e.storageArea !== window.localStorage || (e.key !== KEY && e.key !== null)) return;
    var other = readStore(); if (!other) return;
    items.forEach(function (it) {
      var o = other[it.id], dd = dirty[it.id] || {}; if (!o) return;
      var d = drafts[it.id], likesChanged = false;
      if (!dd.liked && d.liked.join('|') !== o.liked.join('|')) { d.liked = o.liked; likesChanged = true; }
      if (!dd.note && d.note !== o.note) {
        d.note = o.note; it.el.ta.value = o.note; grow(it.el.ta);
        if (FV.open && FV.list[FV.pos] === it) FV.ta.value = o.note;
      }
      if (likesChanged) refreshLikes(it);
    });
    refreshSend();
  });
  function showSaved(it) {
    var el = it.el.saved; if (!el) return;
    el.textContent = !storageOk ? 'Not saved: this browser blocks storage' : (has(it) ? 'saved' : '');
  }
  function has(it) { var d = drafts[it.id]; return d.liked.length > 0 || d.note.trim() !== ''; }
  function count() { return items.filter(has).length; }
  function payloadItems() {
    return items.filter(has).map(function (it) { return { id: it.id, liked: drafts[it.id].liked.slice(), note: drafts[it.id].note }; });
  }

  /* ---------- markdown for the export flow (mirrors the server) ---------- */
  function markdown(list, sentAt) {
    var lines = ['# ' + DATA.title + ': feedback', '', 'Board `' + DATA.id + '`. Sent ' + sentAt + '.', ''], section = null;
    list.forEach(function (e) {
      var it = byId[e.id];
      if (it.section !== section) { section = it.section; lines.push('## ' + section, ''); }
      lines.push('### ' + it.title, '');
      lines.push(e.liked.length ? 'Liked: ' + e.liked.map(function (v) { return it.vById[v].label + ' (`' + v + '`)'; }).join(', ') : 'Liked: none', '');
      if (e.note.trim()) {
        lines.push('Note:', '');
        e.note.replace(/\n+$/, '').split('\n').forEach(function (ln) { lines.push(ln ? '> ' + ln : '>'); });
        lines.push('');
      }
    });
    lines.push((items.length - list.length) + ' of ' + items.length + ' items had no like or note.');
    return lines.join('\n') + '\n';
  }

  /* ---------- image swap: slide and crossfade ---------- */
  function swapImg(host, v, dir, alt, useFull) {
    var old = host.querySelector('img.cur');
    var nu = new Image();
    nu.className = 'cur'; nu.alt = alt; nu.decoding = 'async';
    nu.style.backgroundImage = 'url("' + thumb(v) + '")';
    nu.src = useFull ? full(v) : thumb(v);
    if (!old) { host.appendChild(nu); return nu; }
    host.appendChild(nu);
    old.classList.remove('cur');
    if (reduced() || !old.animate || !dir) { old.remove(); return nu; }
    var d = dir > 0 ? 1 : -1;
    var out = old.animate([{ opacity: 1, transform: 'none' }, { opacity: 0, transform: 'translateX(' + (-d * 26) + 'px)' }], { duration: 170, easing: 'ease-in', fill: 'forwards' });
    out.onfinish = function () { old.remove(); };
    nu.animate([{ opacity: 0, transform: 'translateX(' + (d * 26) + 'px)' }, { opacity: 1, transform: 'none' }], { duration: 230, easing: 'cubic-bezier(.2,.7,.2,1)' });
    return nu;
  }

  /* ---------- page ---------- */
  var app = document.getElementById('app');
  var wrap = h('div', { class: 'wrap' });
  var inflight = false, sendBtn, miniBtn, notice, filterSel, secEls = [], emptyEl, lastSig = null, lastSid = null, sentSig = null, closedRound = false;

  function buildTop() {
    var top = h('header', { class: 'top' });
    top.appendChild(h('h1', { text: DATA.title }));
    top.appendChild(h('p', { class: 'instr', text: DATA.instruction }));
    sendBtn = h('button', { class: 'btn btn-primary send', type: 'button' });
    sendBtn.addEventListener('click', send);
    top.appendChild(sendBtn);
    filterSel = h('select', { id: 'show', 'aria-label': 'Show' }, [
      h('option', { value: 'all', text: 'All' }), h('option', { value: 'new', text: 'Not reviewed yet' }), h('option', { value: 'fb', text: 'Has feedback' })]);
    filterSel.addEventListener('change', applyFilter);
    top.appendChild(h('label', { class: 'show' }, ['Show', filterSel]));
    wrap.appendChild(top);
    notice = h('div', { class: 'notice', role: 'status', hidden: true });
    wrap.appendChild(notice);

    var mini = h('div', { class: 'mini', 'aria-hidden': 'true' });
    miniBtn = h('button', { class: 'btn btn-primary', type: 'button', tabindex: '-1' });
    miniBtn.addEventListener('click', send);
    mini.appendChild(h('div', { class: 'wrap' }, [h('b', { text: DATA.title }), miniBtn]));
    app.appendChild(mini);
    if ('IntersectionObserver' in window) {
      new IntersectionObserver(function (es) {
        var on = !es[0].isIntersecting && es[0].boundingClientRect.top < 0;
        mini.classList.toggle('on', on);
        mini.setAttribute('aria-hidden', on ? 'false' : 'true');
        miniBtn.tabIndex = on ? 0 : -1;
      }).observe(sendBtn);
    }
  }

  function refreshSend() {
    var n = count(), sig = JSON.stringify(payloadItems());
    var done = sentSig !== null && sig === sentSig;
    [sendBtn, miniBtn].forEach(function (b) {
      b.textContent = '';
      b.appendChild(document.createTextNode(inflight ? 'Sending…' : done ? 'Sent' : 'Send feedback'));
      if (!inflight && !done && n) b.appendChild(h('span', { class: 'n', text: ' · ' + n }));
      b.disabled = inflight || done || n === 0;
    });
    if (sentSig !== null && !done && !closedRound && notice.dataset.kind === 'sent') showNotice('');
  }
  function showNotice(msg, kind, action) {
    notice.textContent = ''; notice.dataset.kind = kind || '';
    notice.hidden = !msg; notice.className = 'notice' + (kind === 'err' ? ' err' : '');
    if (!msg) return;
    notice.appendChild(h('span', { text: msg }));
    if (action) { var b = h('button', { class: 'btn', type: 'button', text: action.label }); b.addEventListener('click', function (ev) { action.fn(ev); }); notice.appendChild(b); }
  }

  function buildItem(it) {
    var n = it.versions.length, multi = n > 1, E = it.el;
    var root = h('article', { class: 'item', id: 'item-' + it.dom, 'data-item': it.id });
    var left = h('div', { class: 'left' });
    var stack = h('div', { class: 'stack', tabindex: '0', role: 'group',
      'aria-label': it.title + ', ' + n + (n === 1 ? ' version' : ' versions') + (multi ? '. Up and down arrows switch versions, L likes, Enter opens the full view.' : '. Enter opens the full view.') });
    var deck = h('div', { class: 'deck' });
    if (n > 2) deck.appendChild(h('span', { class: 'edge e2', 'aria-hidden': 'true' }));
    if (multi) deck.appendChild(h('span', { class: 'edge e1', 'aria-hidden': 'true' }));
    var card = h('button', { class: 'card', type: 'button', tabindex: '-1', 'aria-label': 'Open ' + it.title + ' in full view' });
    deck.appendChild(card); stack.appendChild(deck);
    E.likeBtn = h('button', { class: 'likebtn', type: 'button', 'aria-pressed': 'false' });
    E.likeBtn.addEventListener('click', function () { toggleLike(it, it.versions[it.sel].id); });
    stack.appendChild(h('div', { class: 'likebar' }, [E.likeBtn]));
    E.root = root; E.stack = stack; E.card = card;

    var under = h('div', { class: 'under' });
    E.ths = [];
    if (multi) {
      var strip = h('div', { class: 'strip' });
      it.versions.forEach(function (v, i) {
        var th = h('button', { class: 'th', type: 'button', style: '--ar:' + ratio(v), 'aria-label': 'Version ' + v.label }, [
          h('img', { src: thumb(v), alt: '', loading: 'lazy', decoding: 'async' }), h('span', { class: 'lb', text: v.label }), h('span', { class: 'ck', text: '✓', hidden: true })]);
        th.addEventListener('click', function () { setSel(it, i); });
        strip.appendChild(th); E.ths.push(th);
      });
      under.appendChild(strip);
      E.strip = strip;
      E.count = h('span', { text: '' });
      under.appendChild(h('div', { class: 'meta' }, [E.count]));
    } else {
      under.appendChild(h('div', { style: 'flex:1' }));
      under.appendChild(h('div', { class: 'meta' }));
    }
    var fullBtn = h('button', { class: 'btn btn-quiet', type: 'button', text: '⤢ Full view' });
    fullBtn.addEventListener('click', function () { openFull(it, fullBtn); });
    under.lastChild.appendChild(fullBtn);
    stack.appendChild(under);
    stack.appendChild(h('p', { class: 'hint', 'aria-hidden': 'true', text: multi ? '↑ ↓ versions · L like · Enter full view' : 'Enter full view' }));
    left.appendChild(stack);

    var ctx = h('div', { class: 'ctx' });
    ctx.appendChild(h('h3', { text: it.title }));
    E.line = h('p', { class: 'line' });
    ctx.appendChild(E.line);
    E.info = h('details', { class: 'info' }, [h('summary', { text: 'info' })]);
    E.infoBody = h('div'); E.info.appendChild(E.infoBody);
    ctx.appendChild(E.info);
    left.appendChild(ctx);
    root.appendChild(left);

    var fb = h('div', { class: 'fb' });
    E.liked = h('p', { class: 'liked' });
    fb.appendChild(E.liked);
    fb.appendChild(h('p', { class: 'lab', text: 'Note' }));
    E.ta = h('textarea', { class: 'note', rows: '3', placeholder: 'What to keep, change or cut', 'aria-label': 'Note on ' + it.title });
    E.ta.value = drafts[it.id].note;
    E.ta.addEventListener('input', function () { setNote(it, E.ta.value, E.ta); });
    E.ta.addEventListener('keydown', function (e) { if (e.key === 'Enter' && mod(e)) { e.preventDefault(); nextItem(it); } });
    fb.appendChild(E.ta);
    E.saved = h('span', { text: '' });
    fb.appendChild(h('div', { class: 'foot' }, [E.saved, h('span', { text: '⌘↵ next' })]));
    root.appendChild(fb);

    card.addEventListener('click', function () { openFull(it, card); });
    stack.addEventListener('keydown', function (e) { stackKey(e, it); });
    renderItem(it, 0, true);
    return root;
  }

  function renderItem(it, dir, first) {
    var E = it.el, v = it.versions[it.sel];
    E.card.style.setProperty('--ar', ratio(v));
    E.card.parentNode.style.setProperty('--ar', ratio(v));
    if (first) {
      var img = new Image(); img.className = 'cur'; img.alt = it.title + ', version ' + v.label;
      img.loading = 'lazy'; img.decoding = 'async'; img.style.backgroundImage = 'url("' + thumb(v) + '")'; img.src = full(v);
      E.card.appendChild(img);
    } else swapImg(E.card, v, dir, it.title + ', version ' + v.label, true);
    E.ths.forEach(function (th, i) { th.setAttribute('aria-current', i === it.sel ? 'true' : 'false'); });
    if (E.count) E.count.textContent = (it.sel + 1) + ' of ' + it.versions.length;
    E.line.textContent = v.note || ''; E.line.title = v.note || ''; E.line.hidden = !v.note;
    var inf = v.info || {}, parts = [];
    E.infoBody.textContent = '';
    if (inf.file) E.infoBody.appendChild(h('div', { text: inf.file }));
    if (inf.sources && inf.sources.length) E.infoBody.appendChild(h('ul', {}, inf.sources.map(function (s) { return h('li', { text: s }); })));
    if (v.recommended) E.infoBody.appendChild(h('div', { text: 'Recommended by the agent' }));
    E.info.hidden = !(inf.file || (inf.sources && inf.sources.length) || v.recommended);
    refreshLikes(it);
    if (E.strip && E.ths[it.sel] && !first) {
      var th = E.ths[it.sel], s = E.strip;
      var left = th.offsetLeft - s.clientWidth / 2 + th.offsetWidth / 2;
      if (s.scrollTo) s.scrollTo({ left: left, behavior: reduced() ? 'auto' : 'smooth' }); else s.scrollLeft = left;
    }
  }

  function refreshLikes(it) {
    var E = it.el, d = drafts[it.id], v = it.versions[it.sel];
    var on = d.liked.indexOf(v.id) >= 0;
    E.likeBtn.setAttribute('aria-pressed', on ? 'true' : 'false');
    E.likeBtn.textContent = '';
    E.likeBtn.appendChild(h('span', { class: 'heart', 'aria-hidden': 'true', text: on ? '♥' : '♡' }));
    E.likeBtn.appendChild(document.createTextNode(on ? ' Liked' : (it.versions.length > 1 ? ' Like this version' : ' Like this')));
    it.versions.forEach(function (ver, i) {
      if (E.ths[i]) E.ths[i].querySelector('.ck').hidden = d.liked.indexOf(ver.id) < 0;
    });
    E.liked.textContent = '';
    E.liked.appendChild(h('span', { class: 'lab', text: 'Liked' }));
    E.liked.appendChild(document.createTextNode(d.liked.length ? d.liked.map(function (id) { return it.vById[id].label; }).join(', ') : 'none yet'));
    showSaved(it);
  }

  function setSel(it, i, dir) {
    i = Math.max(0, Math.min(it.versions.length - 1, i));
    if (i === it.sel) return;
    var d = dir || (i > it.sel ? 1 : -1);
    it.sel = i;
    renderItem(it, d);
    say('Version ' + it.versions[i].label + ', ' + (i + 1) + ' of ' + it.versions.length);
    if (FV.open && FV.list[FV.pos] === it) fvRender(d);
    preload(it.versions[Math.min(i + 1, it.versions.length - 1)]);
  }
  function preload(v) { if (v) (new Image()).src = full(v); }

  function toggleLike(it, vid) {
    var d = drafts[it.id], k = d.liked.indexOf(vid);
    if (k >= 0) d.liked.splice(k, 1); else { d.liked.push(vid); d.liked.sort(function (a, b) { return order(it, a) - order(it, b); }); }
    changed(it, false);
    say((d.liked.indexOf(vid) >= 0 ? 'Liked version ' : 'Removed like from version ') + it.vById[vid].label);
  }
  function order(it, vid) { return it.versions.indexOf(it.vById[vid]); }
  function setNote(it, text, from) {
    drafts[it.id].note = text;
    if (it.el.ta !== from) { it.el.ta.value = text; }
    grow(it.el.ta);
    if (FV.open && FV.list[FV.pos] === it && FV.ta !== from) { FV.ta.value = text; }
    changed(it, true);
  }
  function changed(it, noteOnly) {
    if (!noteOnly) refreshLikes(it);
    if (FV.open && FV.list[FV.pos] === it) fvSync();
    refreshSend(); persist(it.id, noteOnly ? 'note' : 'liked');
    it.el.saved.textContent = 'saving…';
  }

  /* ---------- filter ---------- */
  function visibleItems() { return items.filter(function (it) { return !it.el.root.hidden; }); }
  function applyFilter() {
    var f = filterSel.value, any = false;
    items.forEach(function (it) {
      var show = f === 'all' || (f === 'new' ? !has(it) : has(it));
      it.el.root.hidden = !show; any = any || show;
    });
    secEls.forEach(function (s) { s.head.hidden = !s.items.some(function (it) { return !it.el.root.hidden; }); });
    emptyEl.hidden = any;
    emptyEl.textContent = f === 'fb' ? 'No feedback yet. Like a version or leave a note.' : 'Everything here has feedback.';
  }

  /* ---------- keyboard: inline ---------- */
  function stackKey(e, it) {
    if (e.metaKey || e.ctrlKey || e.altKey || typing(e.target)) return;
    var k = e.key;
    if (k === 'ArrowDown' || k === 'ArrowRight') { e.preventDefault(); setSel(it, it.sel + 1, 1); }
    else if (k === 'ArrowUp' || k === 'ArrowLeft') { e.preventDefault(); setSel(it, it.sel - 1, -1); }
    else if (k === 'l' || k === 'L') { e.preventDefault(); toggleLike(it, it.versions[it.sel].id); }
    else if ((k === 'Enter' || k === 'f' || k === 'F') && (e.target === it.el.stack || k !== 'Enter')) { e.preventDefault(); openFull(it, it.el.stack); }
  }
  function nextItem(it) {
    var vis = visibleItems(), nx = vis[vis.indexOf(it) + 1];
    if (!nx) { sendBtn.focus(); sendBtn.scrollIntoView({ block: 'center' }); return; }
    nx.el.root.scrollIntoView({ block: 'start', behavior: reduced() ? 'auto' : 'smooth' });
    nx.el.ta.focus({ preventScroll: true });
  }

  /* ---------- full view ---------- */
  var FV = { open: false, list: [], pos: 0, opener: null, last: '' };
  function buildFull() {
    var fv = h('div', { class: 'fv', id: 'fv', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Full view', tabindex: '-1', hidden: true });
    var pos = h('span', { class: 'fv-pos' });
    var keys = h('span', { class: 'fv-keys', 'aria-hidden': 'true' });
    keys.innerHTML = '<kbd>←</kbd> <kbd>→</kbd> graphic · <kbd>↑</kbd> <kbd>↓</kbd> version · <kbd>L</kbd> like · <kbd>N</kbd> note · <kbd>Esc</kbd> close · <kbd>?</kbd> all keys';
    var prev = h('button', { class: 'btn', type: 'button', 'aria-label': 'Previous graphic', text: '‹ Back' });
    var next = h('button', { class: 'btn', type: 'button', 'aria-label': 'Next graphic', text: 'Next ›' });
    var close = h('button', { class: 'btn btn-quiet', type: 'button', text: 'Close ×' });
    prev.addEventListener('click', function () { fvStep(-1); });
    next.addEventListener('click', function () { fvStep(1); });
    close.addEventListener('click', closeFull);
    fv.appendChild(h('div', { class: 'fv-bar' }, [pos, keys, h('div', { class: 'fv-nav' }, [prev, next]), close]));
    var imgHost = h('div', { class: 'fv-img' }), cap = h('div', { class: 'fv-cap' });
    var title = h('h2'), rows = h('div', { class: 'vrows' });
    var ta = h('textarea', { class: 'note', rows: '5', placeholder: 'What to keep, change or cut', 'aria-label': 'Note' });
    var saved = h('span'), rail = h('div', { class: 'fv-rail' }, [title, h('p', { class: 'lab', text: 'Versions' }), rows, h('p', { class: 'lab', text: 'Note' }), ta,
      h('div', { class: 'foot' }, [saved, h('span', { text: '⌘↵ next graphic' })])]);
    ta.addEventListener('input', function () { setNote(FV.list[FV.pos], ta.value, ta); grow(ta); });
    fv.appendChild(h('div', { class: 'fv-main' }, [h('div', { class: 'fv-stage' }, [imgHost, cap]), rail]));
    document.body.appendChild(fv);
    window.addEventListener('resize', fvFit);
    FV.el = fv; FV.pos_ = pos; FV.prev = prev; FV.next = next; FV.imgHost = imgHost; FV.cap = cap; FV.title = title; FV.rows = rows; FV.ta = ta; FV.saved = saved;
  }

  function openFull(it, opener) {
    if (!FV.el) buildFull();
    FV.list = visibleItems(); FV.pos = FV.list.indexOf(it);
    if (FV.pos < 0) { FV.list = items.slice(); FV.pos = items.indexOf(it); }
    FV.opener = opener; FV.open = true; FV.last = ''; FV.itemId = null; FV.imgHost.textContent = '';
    document.getElementById('app').inert = true;
    document.body.classList.add('lock');
    FV.el.hidden = false;
    fvRender(0);
    FV.el.focus();
  }
  function closeFull() {
    if (!FV.open) return;
    closeSheet();
    var it = FV.list[FV.pos];
    FV.open = false; FV.el.hidden = true;
    document.getElementById('app').inert = false;
    document.body.classList.remove('lock');
    var target = FV.opener && document.contains(FV.opener) && FV.opener.closest('[data-item]') && FV.opener.closest('[data-item]').dataset.item === it.id ? FV.opener : it.el.stack;
    if (target === it.el.stack || !document.contains(target)) it.el.root.scrollIntoView({ block: 'center' });
    target.focus({ preventScroll: true });
    refreshSend();
  }
  function fvStep(d) {
    var np = FV.pos + d; if (np < 0 || np >= FV.list.length) return;
    FV.pos = np; fvRender(d);
  }
  function fvRender(dir) {
    var it = FV.list[FV.pos], v = it.versions[it.sel], key = it.id + ':' + it.sel;
    FV.pos_.innerHTML = '<b>' + (FV.pos + 1) + '</b> of ' + FV.list.length;
    FV.prev.disabled = FV.pos === 0; FV.next.disabled = FV.pos === FV.list.length - 1;
    var itemChanged = FV.itemId !== it.id;
    if (itemChanged) {
      FV.itemId = it.id; FV.title.textContent = it.title; FV.rows.textContent = ''; FV.vrows = [];
      it.versions.forEach(function (ver, i) {
        var sel = h('button', { class: 'vsel', type: 'button' }, [h('span', { class: 'k', text: i < 9 ? String(i + 1) : '' }), h('span', { class: 'l', text: ver.label }), h('span', { class: 't', text: ver.note || '' })]);
        var lk = h('button', { class: 'like', type: 'button', 'aria-pressed': 'false', 'aria-label': 'Like version ' + ver.label, text: 'Like' });
        sel.addEventListener('click', function () { setSel(it, i); });
        lk.addEventListener('click', function () { toggleLike(it, ver.id); });
        var row = h('div', { class: 'vrow' }, [sel, lk]); FV.rows.appendChild(row); FV.vrows.push({ row: row, lk: lk });
      });
      FV.ta.value = drafts[it.id].note; grow(FV.ta);
    }
    if (FV.last !== key) {
      var img = swapImg(FV.imgHost, v, itemChanged ? dir : (dir || 0), it.title + ', version ' + v.label, true);
      img.onload = fvFit; img.style.width = '1px'; img.style.height = '1px'; img.dataset.w = v.w; img.dataset.h = v.h;
      fvFit();
      FV.last = key;
      var nxt = FV.list[FV.pos + 1]; if (nxt) preload(nxt.versions[nxt.sel]);
      var pv = FV.list[FV.pos - 1]; if (pv) preload(pv.versions[pv.sel]);
    }
    FV.cap.innerHTML = '';
    FV.cap.appendChild(h('b', { text: v.label }));
    FV.cap.appendChild(document.createTextNode(it.versions.length > 1 ? ' (' + (it.sel + 1) + ' of ' + it.versions.length + ')' : ''));
    if (v.note) FV.cap.appendChild(document.createTextNode('  ·  ' + v.note));
    fvSync();
  }
  function fvSync() {
    var it = FV.list[FV.pos];
    FV.vrows.forEach(function (r, i) {
      r.row.setAttribute('aria-current', i === it.sel ? 'true' : 'false');
      var on = drafts[it.id].liked.indexOf(it.versions[i].id) >= 0;
      r.lk.setAttribute('aria-pressed', on ? 'true' : 'false');
      r.lk.textContent = 'Like';
    });
    FV.saved.textContent = it.el.saved.textContent;
  }
  function fvFit() {
    if (!FV.open) return;
    var cw = FV.imgHost.clientWidth, ch = FV.imgHost.clientHeight;
    FV.imgHost.querySelectorAll('img').forEach(function (img) {
      var w = +img.dataset.w, hh = +img.dataset.h; if (!w || !hh || !cw || !ch) return;
      var s = Math.min((cw - 4) / w, (ch - 4) / hh);
      img.style.width = Math.floor(w * s) + 'px'; img.style.height = Math.floor(hh * s) + 'px';
    });
  }

  var sheet = null;
  function toggleSheet() { if (sheet) closeSheet(); else openSheet(); }
  function openSheet() {
    var rows = [['← →', 'Previous or next graphic'], ['↑ ↓', 'Previous or next version'], ['1 to 9', 'Jump to a version'], ['L', 'Like or unlike this version'],
      ['N', 'Write a note'], ['⌘/Ctrl ↵', 'Save and go to the next graphic'], ['Esc', 'Leave the note, then close'], ['?', 'This list']];
    var dl = h('dl');
    rows.forEach(function (r) { dl.appendChild(h('dt', {}, [h('kbd', { text: r[0] })])); dl.appendChild(h('dd', { text: r[1] })); });
    sheet = h('div', { class: 'sheet', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Keyboard shortcuts' }, [h('div', { class: 'sheet-card' }, [h('h2', { text: 'Keyboard shortcuts' }), dl])]);
    sheet.addEventListener('mousedown', function (e) { if (e.target === sheet) closeSheet(); });
    sheet.tabIndex = -1;
    FV.el.appendChild(sheet);
    sheet.focus();
  }
  function closeSheet() { if (sheet) { sheet.remove(); sheet = null; if (FV.open && FV.el) FV.el.focus(); } }

  function trap(e, root) {
    var f = Array.prototype.filter.call(root.querySelectorAll('a[href],button:not([disabled]),input,textarea,select,[tabindex]'),
      function (el) { return el.offsetParent !== null && el.tabIndex >= 0; });
    if (!f.length) { e.preventDefault(); if (root.focus) root.focus(); return; }
    var a = f[0], z = f[f.length - 1];
    if (!root.contains(document.activeElement)) { e.preventDefault(); a.focus(); }
    else if (e.shiftKey && (document.activeElement === a || document.activeElement === root)) { e.preventDefault(); z.focus(); }
    else if (!e.shiftKey && document.activeElement === z) { e.preventDefault(); a.focus(); }
  }

  function fvKey(e) {
    var t = e.target, isTyping = typing(t), it = FV.list[FV.pos], k = e.key;
    if (k === 'Tab') return trap(e, sheet || FV.el);
    if (k === 'Enter' && mod(e)) {
      e.preventDefault(); var wasTyping = isTyping;
      if (FV.pos < FV.list.length - 1) { fvStep(1); if (wasTyping) FV.ta.focus({ preventScroll: true }); } else if (isTyping) FV.ta.blur();
      return;
    }
    if (k === 'Escape') {
      e.preventDefault();
      if (sheet) closeSheet(); else if (isTyping) { t.blur(); FV.el.focus(); } else closeFull();
      return;
    }
    if (isTyping || e.metaKey || e.ctrlKey || e.altKey) return;
    if (k === '?' || (k === '/' && e.shiftKey)) { e.preventDefault(); toggleSheet(); return; }
    if (sheet) return;
    if (k === 'ArrowRight') { e.preventDefault(); fvStep(1); }
    else if (k === 'ArrowLeft') { e.preventDefault(); fvStep(-1); }
    else if (k === 'ArrowDown') { e.preventDefault(); setSel(it, it.sel + 1, 1); }
    else if (k === 'ArrowUp') { e.preventDefault(); setSel(it, it.sel - 1, -1); }
    else if (/^[1-9]$/.test(k)) { if (+k <= it.versions.length) { e.preventDefault(); setSel(it, +k - 1); } }
    else if (k === 'l' || k === 'L') { e.preventDefault(); toggleLike(it, it.versions[it.sel].id); }
    else if (k === 'n' || k === 'N') { e.preventDefault(); FV.ta.focus(); }
  }

  /* ---------- send and export ---------- */
  var EX = { open: false };
  function docFor(list, sid) {
    return { board: DATA.id, revision: REV, submission_id: sid, sent_at: nowIso(),
      items: list.map(function (e) { return { id: e.id, title: byId[e.id].title, liked: e.liked, note: e.note }; }) };
  }
  function checkRevision(cb) {
    /* file mode: board-rev.js sits beside board.html and names the newest build */
    var sc = document.createElement('script');
    sc.src = 'board-rev.js?t=' + Date.now();
    sc.onload = function () { sc.remove(); cb(!window.__RB_REV || window.__RB_REV === REV); };
    sc.onerror = function () { sc.remove(); cb(true); };
    document.head.appendChild(sc);
  }
  function staleNotice() {
    showNotice('This board was rebuilt. Reload; your notes are kept.', 'err', { label: 'Reload', fn: function () { location.reload(); } });
  }
  function copyMarkdown(list, btn) {
    var md = markdown(list, nowIso());
    var p = navigator.clipboard && navigator.clipboard.writeText ? navigator.clipboard.writeText(md) : Promise.reject();
    p.then(function () { btn.textContent = 'Copied'; },
      function () { exportPanel('file', list); });
  }
  function sendFile(list, sig) {
    inflight = true; refreshSend();
    checkRevision(function (fresh) {
      inflight = false;
      if (!fresh) { refreshSend(); staleNotice(); return; }
      if (sig !== lastSig) { lastSig = sig; lastSid = uid(); }
      var doc = docFor(list, lastSid);
      var name = 'review-feedback__' + safeName(DATA.id) + '__' + REV + '__' + safeName(lastSid) + '.json';
      var a = h('a', { download: name, href: URL.createObjectURL(new Blob([JSON.stringify(doc, null, 2)], { type: 'application/json' })) });
      document.body.appendChild(a); a.click(); a.remove();
      sentSig = sig;
      showNotice('Saved to your Downloads. Your notes are on their way back to the session.', 'sent', { label: 'Copy as Markdown', fn: function (ev) { copyMarkdown(list, ev.currentTarget); } });
      refreshSend(); window.scrollTo({ top: 0, behavior: reduced() ? 'auto' : 'smooth' });
    });
  }
  function send() {
    if (inflight) return;
    var list = payloadItems(); if (!list.length) return;
    var sig = JSON.stringify(list);
    if (!SERVED) return sendFile(list, sig);
    if (sig !== lastSig) { lastSig = sig; lastSid = uid(); }
    inflight = true; refreshSend();
    fetch('/api/feedback', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-RB-Token': TOKEN },
      body: JSON.stringify({ board: DATA.id, revision: REV, submission_id: lastSid, items: list }) })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) { return { r: r, j: j }; }); })
      .then(function (x) {
        inflight = false;
        if (x.r.ok) {
          sentSig = sig; closedRound = !!x.j.closed;
          showNotice('Sent. Your notes are back in the session.', 'sent');
          refreshSend(); window.scrollTo({ top: 0, behavior: reduced() ? 'auto' : 'smooth' });
        } else if (x.r.status === 409) {
          refreshSend(); staleNotice();
        } else if (x.r.status === 410) {
          closedRound = true; refreshSend();
          showNotice('This round is closed. Your first send was saved.', 'err');
        } else { refreshSend(); exportPanel('error', list, x.j.error); }
      })
      .catch(function () { inflight = false; refreshSend(); exportPanel('net', list); });
  }

  function exportPanel(why, list, detail) {
    var md = markdown(list, nowIso());
    var doc = docFor(list, lastSid || uid());
    var heads = { file: 'Copy your feedback', net: 'Could not reach the review server', error: 'The review server said no' };
    var lead = { file: 'The browser would not let this page copy automatically. Copy the notes and paste them into the chat.',
      net: 'Your notes are kept in this browser. Copy them and paste them into the chat.',
      error: (detail || 'The send failed') + '. Your notes are kept. Copy them and paste them into the chat.' };
    var status = h('p', { class: 'status', role: 'status', text: '' });
    var ta = h('textarea', { readonly: true, 'aria-label': 'Feedback as Markdown' }); ta.value = md;
    var copy = h('button', { class: 'btn', type: 'button', text: 'Copy again' });
    var dl = h('button', { class: 'btn', type: 'button', text: 'Download JSON' });
    var close = h('button', { class: 'btn btn-quiet', type: 'button', text: 'Close' });
    function doCopy() {
      var p = navigator.clipboard && navigator.clipboard.writeText ? navigator.clipboard.writeText(md) : Promise.reject();
      p.then(function () { status.textContent = 'Copied. Paste it into the chat.'; },
        function () { ta.focus(); ta.select(); status.textContent = 'Could not copy automatically. The text is selected: press ⌘C or Ctrl+C.'; });
    }
    copy.addEventListener('click', doCopy);
    dl.addEventListener('click', function () {
      var a = h('a', { download: 'review-feedback__' + safeName(DATA.id) + '__' + REV + '__' + safeName(doc.submission_id) + '.json', href: URL.createObjectURL(new Blob([JSON.stringify(doc, null, 2)], { type: 'application/json' })) });
      document.body.appendChild(a); a.click(); a.remove(); status.textContent = 'Downloaded the JSON.';
    });
    var card = h('div', { class: 'ex-card', role: 'dialog', 'aria-modal': 'true', 'aria-label': heads[why], tabindex: '-1' }, [
      h('h2', { text: heads[why] }), h('p', { text: lead[why] }), status, ta, h('div', { class: 'ex-acts' }, [copy, dl, close])]);
    var back = h('div', { class: 'ex' }, [card]);
    var opener = document.activeElement;
    function done() { EX.open = false; back.remove(); document.getElementById('app').inert = false; if (!FV.open) document.body.classList.remove('lock'); if (opener && opener.focus) opener.focus(); }
    close.addEventListener('click', done);
    back.addEventListener('mousedown', function (e) { if (e.target === back) done(); });
    EX = { open: true, close: done, card: card };
    document.body.appendChild(back); document.getElementById('app').inert = true; document.body.classList.add('lock');
    card.focus(); doCopy();
  }

  /* ---------- global keys ---------- */
  document.addEventListener('keydown', function (e) {
    if (EX.open) {
      if (e.key === 'Escape') { e.preventDefault(); EX.close(); } else if (e.key === 'Tab') trap(e, EX.card);
      return;
    }
    if (FV.open) fvKey(e);
  });

  if (!SERVED) window.addEventListener('focus', function () { checkRevision(function (fresh) { if (!fresh) staleNotice(); }); });

  /* ---------- go ---------- */
  buildTop();
  var secWrap = h('main');
  DATA.sections.forEach(function (s) {
    var head = h('h2', { class: 'sec', text: s.name });
    secWrap.appendChild(head);
    var rec = { head: head, items: [] };
    s.items.forEach(function (it) { secWrap.appendChild(buildItem(it)); rec.items.push(it); });
    secEls.push(rec);
  });
  emptyEl = h('p', { class: 'empty', hidden: true });
  secWrap.appendChild(emptyEl);
  wrap.appendChild(secWrap);
  app.appendChild(wrap);
  items.forEach(function (it) { grow(it.el.ta); });
  refreshSend();
  if (skippedDrafts && storageOk) showNotice('Some saved drafts could not be read and were skipped.', 'err');
  if (!storageOk) showNotice('Your browser blocks storage, so drafts will not survive a reload. Send before closing the tab.', 'err');
  window.addEventListener('load', function () { items.forEach(function (it) { grow(it.el.ta); }); });
})();
