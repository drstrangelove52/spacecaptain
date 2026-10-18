/*
 * Bauplan des Inventar-Moduls (Etappe 4): zeichnet Gebäude, Stockwerke, Räume, Bereiche, Möbel und Maschinen als Rechtecke
 * (Einheit: cm) in ein SVG. Wird vom LabManager (bearbeitbar) und von der Gäste-Seite inventar.html (nur ansehen) geladen.
 *
 *   const plan = InvPlan.mount(container, data, { editable, onChange(kind, id, rect|null), onSelect(sel|null), onFloor(id) });
 *   plan.setData(data); plan.setHighlight({ codes: ['ELE-M02'], machineIds: [3], areaCodes: ['ELE'] });
 *   plan.setFloor(id); plan.floorId(); plan.select(kind, id); plan.place(kind, id, {x, y}|null);
 *   plan.update(kind, id, {x, w, rot, floor_id …}); plan.remove(kind, id);
 *
 * kind: 'room' (Raum oder Treppe), 'area', 'furniture', 'machine'.
 * `data` kommt von GET /api/inventory/plan bzw. /api/inventory-public/plan. Elemente stehen auf genau einem Stockwerk
 * (`plan.floor_id`); eine Treppe liegt auf einem Stockwerk und erscheint zusätzlich auf ihrem Ziel-Stockwerk.
 * Die Seite stellt die CSS-Variablen --text, --border, --surface, --surface2, --accent, --body bereit.
 */
(function () {
  const NS = 'http://www.w3.org/2000/svg';
  const SNAP = 5;                                            // cm
  const DEFAULT_SIZE = { area: [300, 300], machine: [80, 60], furniture: { schrank: [100, 50], regal: [100, 40], wand: [150, 15], tisch: [160, 80] } };
  const KIND_ORDER = ['room', 'area', 'furniture', 'machine'];   // von unten nach oben

  function svgEl(tag, attrs, parent) {
    const e = document.createElementNS(NS, tag);
    for (const k in (attrs || {})) if (attrs[k] != null) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  const snap = (v) => Math.round(v / SNAP) * SNAP;
  const furnitureCode = (code) => { const m = /^([A-Z0-9]{3}-M\d{2})/.exec(code || ''); return m ? m[1] : null; };

  function ensureStyle() {
    if (document.getElementById('invplan-style')) return;
    const st = document.createElement('style');
    st.id = 'invplan-style';
    st.textContent = `
      .invplan-wrap{border:1px solid var(--border);border-radius:10px;background:var(--surface2);overflow:auto;max-height:78vh}
      .invplan-svg{display:block;font-family:var(--body,sans-serif);user-select:none;-webkit-user-select:none}
      .invplan-floors{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px}
      .invplan-floor{padding:6px 14px;border:1px solid var(--border);border-radius:16px;cursor:pointer;font-size:15px;font-weight:600;color:var(--text);background:var(--surface)}
      .invplan-floor.on{border-color:var(--accent);color:var(--accent)}
      .invplan-el{cursor:default}.invplan-edit .invplan-el{cursor:move}
      .invplan-dim{opacity:.28}
      .invplan-hit .invplan-shape{stroke:var(--accent,#f4a622)!important;stroke-width:5!important}
      .invplan-hit .invplan-pulse{animation:invplan-pulse 1.3s ease-in-out infinite}
      @keyframes invplan-pulse{0%,100%{opacity:.15}50%{opacity:.75}}
      .invplan-sel .invplan-shape{stroke:var(--text,#fff)!important;stroke-width:4!important;stroke-dasharray:14 8}
      .invplan-handle{fill:var(--accent,#f4a622);stroke:#000;stroke-width:2;cursor:nwse-resize}`;
    document.head.appendChild(st);
  }

  function mount(container, data, opts) {
    opts = opts || {};
    ensureStyle();
    container.innerHTML = '';
    const bar = document.createElement('div');
    bar.className = 'invplan-floors';
    container.appendChild(bar);
    const wrap = document.createElement('div');
    wrap.className = 'invplan-wrap';
    container.appendChild(wrap);
    const svg = svgEl('svg', { class: 'invplan-svg' + (opts.editable ? ' invplan-edit' : '') });
    svg.style.width = '100%';
    if (opts.editable) svg.style.touchAction = 'none';
    wrap.appendChild(svg);

    let sel = null;                                          // { kind, id }
    let floor = null;                                        // aktuelles Stockwerk (id)
    let hl = { codes: [], machineIds: [], areaCodes: [] };
    let drag = null;                                         // { mode: 'move'|'resize', kind, id, start, orig }

    const floors = () => data.floors && data.floors.length ? data.floors : [{ id: 0, name: '' }];
    const list = (kind) => kind === 'room' ? (data.rooms || []) : kind === 'area' ? data.areas : kind === 'furniture' ? data.furniture : data.machines;
    const find = (kind, id) => list(kind).find(o => o.id === id);
    const floorOf = (kind, o) => kind === 'room' ? o.floor_id : (o.plan && o.plan.floor_id != null ? o.plan.floor_id : floors()[0].id);
    const ensureFloor = () => { if (!floors().some(f => f.id === floor)) floor = floors()[0].id; };

    function isHit(kind, o) {
      if (kind === 'furniture') return hl.codes.some(c => furnitureCode(c) === o.code);
      if (kind === 'machine') return hl.machineIds.includes(o.id);
      if (kind === 'area') return !!o.code && hl.areaCodes.includes(o.code);
      return false;
    }
    const anyHl = () => hl.codes.length + hl.machineIds.length + hl.areaCodes.length > 0;
    const visible = (kind, o) => !!o.plan && (kind === 'room'
      ? (o.floor_id === floor || (o.kind === 'treppe' && o.link_floor_id === floor))
      : floorOf(kind, o) === floor);

    function labelFor(kind, o) {
      if (kind === 'furniture') return o.code.replace(/^[A-Z0-9]{3}-/, '') + (o.title && o.title !== o.code ? ' ' + o.title : '');
      if (kind === 'area') return (o.code ? o.code + ' ' : '') + o.name;
      return o.name;
    }

    function renderBar() {
      bar.innerHTML = '';
      bar.style.display = floors().length > 1 ? '' : 'none';
      for (const f of floors()) {
        const b = document.createElement('div');
        b.className = 'invplan-floor' + (f.id === floor ? ' on' : '');
        b.textContent = f.name;
        b.onclick = () => api.setFloor(f.id);
        bar.appendChild(b);
      }
    }

    function render() {
      ensureFloor();
      renderBar();
      const r = data.room, W = r.width_cm, H = r.height_cm;
      svg.setAttribute('viewBox', `${-20} ${-20} ${W + 40} ${H + 40}`);
      svg.innerHTML = '';
      const defs = svgEl('defs', {}, svg);
      const pat = svgEl('pattern', { id: 'invplan-grid', width: 100, height: 100, patternUnits: 'userSpaceOnUse' }, defs);
      svgEl('path', { d: 'M100 0H0V100', fill: 'none', stroke: 'currentColor', 'stroke-opacity': .12, 'stroke-width': 1 }, pat);
      const st = svgEl('pattern', { id: 'invplan-stairs', width: 24, height: 24, patternUnits: 'userSpaceOnUse' }, defs);
      svgEl('path', { d: 'M0 12H24', stroke: 'currentColor', 'stroke-opacity': .55, 'stroke-width': 3 }, st);
      svgEl('rect', { x: 0, y: 0, width: W, height: H, fill: 'var(--surface2)', stroke: 'var(--text)', 'stroke-width': 2, 'stroke-opacity': .25, 'stroke-dasharray': '12 8' }, svg);
      svgEl('rect', { x: 0, y: 0, width: W, height: H, fill: 'url(#invplan-grid)', style: 'color:var(--text)', 'pointer-events': 'none' }, svg);
      const fname = (floors().find(f => f.id === floor) || {}).name;
      const t = svgEl('text', { x: 8, y: H - 10, 'font-size': 18, fill: 'var(--text)', 'fill-opacity': .45 }, svg);
      t.textContent = `${r.name}${fname ? ' · ' + fname : ''} · ${(W / 100).toLocaleString('de-CH')} × ${(H / 100).toLocaleString('de-CH')} m`;

      // Räume anderer Stockwerke als Schatten (Orientierung), nicht anklickbar
      for (const o of list('room')) {
        if (!o.plan || o.kind === 'treppe' || o.floor_id === floor) continue;
        const p = o.plan;
        svgEl('rect', { x: p.x, y: p.y, width: p.w, height: p.h, fill: 'none', stroke: 'var(--text)', 'stroke-opacity': .22, 'stroke-width': 3,
          'stroke-dasharray': '16 10', 'pointer-events': 'none' }, svg);
      }
      for (const kind of KIND_ORDER) {
        for (const o of list(kind)) {
          if (visible(kind, o)) drawElement(kind, o);
        }
      }
      if (opts.editable && sel) drawHandle();
    }

    function drawElement(kind, o) {
      const p = o.plan, cx = p.x + p.w / 2, cy = p.y + p.h / 2;
      const hit = isHit(kind, o);
      const cls = ['invplan-el'];
      if (anyHl() && kind !== 'room') cls.push(hit ? 'invplan-hit' : 'invplan-dim');
      if (sel && sel.kind === kind && sel.id === o.id) cls.push('invplan-sel');
      const g = svgEl('g', { class: cls.join(' '), 'data-kind': kind, 'data-id': o.id, transform: `rotate(${p.rot || 0} ${cx} ${cy})` }, svg);
      const rot = ((p.rot || 0) % 180 + 180) % 180;
      const vw = rot === 90 ? p.h : p.w, vh = rot === 90 ? p.w : p.h;

      if (kind === 'room') {
        const stairs = o.kind === 'treppe';
        svgEl('rect', { class: 'invplan-shape', x: p.x, y: p.y, width: p.w, height: p.h, fill: 'var(--surface)', 'fill-opacity': stairs ? .9 : .65,
          stroke: 'var(--text)', 'stroke-opacity': .75, 'stroke-width': stairs ? 3 : 6 }, g);
        if (stairs) svgEl('rect', { x: p.x, y: p.y, width: p.w, height: p.h, fill: 'url(#invplan-stairs)', style: 'color:var(--text)', 'pointer-events': 'none' }, g);
        let txt = o.name;
        if (stairs && o.link_floor_id != null) {
          const target = o.floor_id === floor ? o.link_floor_id : o.floor_id;
          const ti = floors().findIndex(f => f.id === target), ci = floors().findIndex(f => f.id === floor);
          txt += ` ${ti > ci ? '↑' : '↓'} ${(floors()[ti] || {}).name || ''}`;
        }
        const size = Math.max(10, Math.min(22, vh * 0.5, vw * 1.7 / Math.max(txt.length, 3)));
        const tx = svgEl('text', stairs ? { x: cx, y: cy + size * 0.35, 'text-anchor': 'middle', 'font-size': size, 'font-weight': 700, fill: 'var(--text)',
          transform: `rotate(${-(p.rot || 0)} ${cx} ${cy})`, 'pointer-events': 'none', stroke: 'var(--surface)', 'stroke-width': 4, 'paint-order': 'stroke' }
          : { x: p.x + 10, y: p.y + size + 6, 'font-size': size, 'font-weight': 700, fill: 'var(--text)', 'fill-opacity': .7, 'pointer-events': 'none' }, g);
        tx.textContent = txt;
        return;
      }

      const color = o.color || '#22d3ee';
      const fill = kind === 'area' ? { 'fill-opacity': .16 } : kind === 'furniture' ? { 'fill-opacity': .5 } : { 'fill-opacity': .95 };
      svgEl('rect', Object.assign({ class: 'invplan-shape', x: p.x, y: p.y, width: p.w, height: p.h, rx: kind === 'machine' ? 8 : 2, fill: color,
        stroke: color, 'stroke-width': kind === 'area' ? 3 : 2, 'stroke-dasharray': kind === 'area' ? '10 6' : null }, fill), g);
      if (hit) svgEl('rect', { class: 'invplan-pulse', x: p.x - 8, y: p.y - 8, width: p.w + 16, height: p.h + 16, rx: 10, fill: 'none', stroke: 'var(--accent)', 'stroke-width': 6, 'pointer-events': 'none' }, g);
      // Beschriftung bleibt waagrecht (gegen die Drehung des Elements gedreht) und passt in die sichtbare Breite
      const txt = labelFor(kind, o);
      const size = Math.max(9, Math.min(22, vh * 0.6, vw * 1.7 / Math.max(txt.length, 3)));
      if (kind === 'area') {                                 // Bereichsname oben links, ungedreht
        const a = svgEl('text', { x: p.x + 8, y: p.y + size + 4, 'font-size': size, 'font-weight': 700, fill: 'var(--text)', 'fill-opacity': .8, 'pointer-events': 'none' }, g);
        a.textContent = txt;
      } else {
        const tx = svgEl('text', { x: cx, y: cy + size * 0.35, 'font-size': size, 'font-weight': 700, 'text-anchor': 'middle', fill: kind === 'machine' ? '#000' : 'var(--text)',
          transform: `rotate(${-(p.rot || 0)} ${cx} ${cy})`, 'pointer-events': 'none' }, g);
        tx.textContent = txt;
      }
    }

    function drawHandle() {
      const o = find(sel.kind, sel.id);
      if (!o || !o.plan || !visible(sel.kind, o)) return;
      const p = o.plan, cx = p.x + p.w / 2, cy = p.y + p.h / 2;
      const g = svgEl('g', { transform: `rotate(${p.rot || 0} ${cx} ${cy})` }, svg);
      svgEl('circle', { class: 'invplan-handle', cx: p.x + p.w, cy: p.y + p.h, r: 11, 'data-handle': 1 }, g);
    }

    // ── Zeigerlogik (nur bearbeitbar) ──
    function toCm(ev) {
      const pt = svg.createSVGPoint();
      pt.x = ev.clientX; pt.y = ev.clientY;
      const m = svg.getScreenCTM();
      return m ? pt.matrixTransform(m.inverse()) : { x: 0, y: 0 };
    }
    function rotateBack(pt, o) {                             // Punkt ins Eigensystem des (gedrehten) Elements
      const p = o.plan, cx = p.x + p.w / 2, cy = p.y + p.h / 2, a = -(p.rot || 0) * Math.PI / 180;
      const dx = pt.x - cx, dy = pt.y - cy;
      return { x: cx + dx * Math.cos(a) - dy * Math.sin(a), y: cy + dx * Math.sin(a) + dy * Math.cos(a) };
    }
    const selInfo = () => sel && find(sel.kind, sel.id) ? { kind: sel.kind, id: sel.id, item: find(sel.kind, sel.id) } : null;
    function setSelection(next) {
      sel = next;
      render();
      if (opts.onSelect) opts.onSelect(selInfo());
    }

    if (opts.editable) {
      svg.addEventListener('pointerdown', (ev) => {
        const pt = toCm(ev);
        if (ev.target.getAttribute && ev.target.getAttribute('data-handle') && sel) {
          const o = find(sel.kind, sel.id);
          drag = { mode: 'resize', kind: sel.kind, id: sel.id, orig: Object.assign({}, o.plan) };
          svg.setPointerCapture(ev.pointerId);
          return;
        }
        const g = ev.target.closest && ev.target.closest('[data-kind]');
        if (!g) { setSelection(null); return; }
        const kind = g.getAttribute('data-kind'), id = +g.getAttribute('data-id');
        if (!sel || sel.kind !== kind || sel.id !== id) setSelection({ kind, id });
        drag = { mode: 'move', kind, id, start: pt, orig: Object.assign({}, find(kind, id).plan), moved: false };
        svg.setPointerCapture(ev.pointerId);
      });
      svg.addEventListener('pointermove', (ev) => {
        if (!drag) return;
        const o = find(drag.kind, drag.id), pt = toCm(ev);
        if (drag.mode === 'move') {
          const dx = pt.x - drag.start.x, dy = pt.y - drag.start.y;
          if (!drag.moved && Math.hypot(dx, dy) < 3) return;
          drag.moved = true;
          o.plan.x = snap(drag.orig.x + dx);
          o.plan.y = snap(drag.orig.y + dy);
        } else {                                             // Grösse: symmetrisch um die Mitte, im Eigensystem des Elements
          const c = { x: drag.orig.x + drag.orig.w / 2, y: drag.orig.y + drag.orig.h / 2 };
          const loc = rotateBack(pt, { plan: drag.orig });
          const w = Math.max(10, snap(Math.abs(loc.x - c.x) * 2)), h = Math.max(10, snap(Math.abs(loc.y - c.y) * 2));
          o.plan.w = w; o.plan.h = h;
          o.plan.x = c.x - w / 2; o.plan.y = c.y - h / 2;
        }
        render();
      });
      const end = () => {
        if (!drag) return;
        const d = drag; drag = null;
        const o = find(d.kind, d.id);
        if ((d.mode === 'move' && d.moved) || d.mode === 'resize') { emit(d.kind, o); if (opts.onSelect) opts.onSelect(selInfo()); }
      };
      svg.addEventListener('pointerup', end);
      svg.addEventListener('pointercancel', end);
    }

    function emit(kind, o) { if (opts.onChange) opts.onChange(kind, o.id, o.plan); }

    const api = {
      el: svg,
      setData(d) {
        data = d;
        if (sel) { const o = find(sel.kind, sel.id); if (!o || !o.plan) sel = null; }
        render();
      },
      setFloor(id) {
        floor = id;
        if (sel) { const o = find(sel.kind, sel.id); if (!o || !visible(sel.kind, o)) sel = null; }
        render();
        if (opts.onFloor) opts.onFloor(floor);
        if (opts.onSelect) opts.onSelect(selInfo());
      },
      floorId() { ensureFloor(); return floor; },
      setHighlight(h) {
        hl = Object.assign({ codes: [], machineIds: [], areaCodes: [] }, h || {});
        if (anyHl()) {                                       // Treffer auf einem anderen Stockwerk: dorthin wechseln
          const hits = [];
          for (const k of ['furniture', 'machine', 'area']) for (const o of list(k)) if (o.plan && isHit(k, o)) hits.push(floorOf(k, o));
          if (hits.length && !hits.includes(floor)) { floor = hits[0]; if (opts.onFloor) opts.onFloor(floor); }
        }
        render();
      },
      select(kind, id) { setSelection(kind ? { kind, id } : null); },
      selected: selInfo,
      clientToCm: toCm,
      scrollToHighlight() {                                  // markiertes Element in die Mitte des Ausschnitts holen (Handy)
        const hit = svg.querySelector('.invplan-hit');
        if (!hit) return;
        const a = hit.getBoundingClientRect(), b = wrap.getBoundingClientRect();
        wrap.scrollLeft += (a.left + a.width / 2) - (b.left + b.width / 2);
        wrap.scrollTop += (a.top + a.height / 2) - (b.top + b.height / 2);
      },
      place(kind, id, at) {                                  // unplatziertes Element auf das aktuelle Stockwerk setzen
        const o = find(kind, id); if (!o) return;
        const sz = kind === 'furniture' ? (DEFAULT_SIZE.furniture[o.kind] || [100, 50]) : DEFAULT_SIZE[kind];
        const c = at || { x: data.room.width_cm / 2, y: data.room.height_cm / 2 };
        ensureFloor();
        o.plan = { x: snap(c.x - sz[0] / 2), y: snap(c.y - sz[1] / 2), w: sz[0], h: sz[1], rot: 0, floor_id: floor };
        emit(kind, o); setSelection({ kind, id });
      },
      update(kind, id, patch) {
        const o = find(kind, id); if (!o || !o.plan) return;
        Object.assign(o.plan, patch);
        if (kind !== 'room' && patch.floor_id != null && patch.floor_id !== floor) sel = null;      // auf anderes Stockwerk verschoben
        render(); emit(kind, o);
        if (opts.onSelect) opts.onSelect(selInfo());
      },
      remove(kind, id) {
        const o = find(kind, id); if (!o) return;
        o.plan = null;
        if (sel && sel.kind === kind && sel.id === id) sel = null;
        render(); if (opts.onChange) opts.onChange(kind, id, null);
        if (opts.onSelect) opts.onSelect(selInfo());
      },
    };
    render();
    return api;
  }

  window.InvPlan = { mount, furnitureCode };
})();
