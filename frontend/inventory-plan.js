/*
 * Bauplan des Inventar-Moduls (Etappe 4): zeichnet Gebäude, Stockwerke, Räume, Bereiche, Möbel und Maschinen als Rechtecke
 * (Einheit: cm) in ein SVG. Wird vom LabManager (bearbeitbar) und von der Gäste-Seite inventar.html (nur ansehen) geladen.
 *
 *   const plan = InvPlan.mount(container, data, { editable, onChange(kind, id, rect|null, extra), onSelect(sel|null), onFloor(id) });
 *   plan.setData(data); plan.setHighlight({ codes: ['ELE-M02'], machineIds: [3], areaCodes: ['ELE'] });
 *   plan.setFloor(id); plan.floorId(); plan.select(kind, id); plan.place(kind, id, {x, y}|null);
 *   plan.update(kind, id, {x, w, rot, floor_id …}); plan.remove(kind, id); plan.toPolygon(id); plan.toRect(id);
 *
 * kind: 'room' (Raum, Treppe, Tür oder Durchgang; Räume optional als Vieleck mit `points`), 'area', 'furniture', 'machine'.
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
  const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi);
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
      let x0 = 0, y0 = 0, x1 = W, y1 = H;                      // Ansicht: Gebäude plus alles, was darüber hinausragt
      for (const kind of KIND_ORDER) for (const o of list(kind)) {
        if (!visible(kind, o)) continue;
        const p = o.plan, a = (p.rot || 0) * Math.PI / 180, cx = p.x + p.w / 2, cy = p.y + p.h / 2;
        const ex = (Math.abs(p.w * Math.cos(a)) + Math.abs(p.h * Math.sin(a))) / 2, ey = (Math.abs(p.w * Math.sin(a)) + Math.abs(p.h * Math.cos(a))) / 2;
        x0 = Math.min(x0, cx - ex); x1 = Math.max(x1, cx + ex); y0 = Math.min(y0, cy - ey); y1 = Math.max(y1, cy + ey);
      }
      svg.setAttribute('viewBox', `${x0 - 20} ${y0 - 20} ${x1 - x0 + 40} ${y1 - y0 + 40}`);
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
      const weight = (kind, o) => kind === 'room' ? (o.kind === 'raum' ? 0 : o.kind === 'treppe' ? 1 : 2) : 0;
      for (const kind of KIND_ORDER) {
        for (const o of list(kind).filter(x => visible(kind, x)).sort((a, b) => weight(kind, a) - weight(kind, b))) drawElement(kind, o);
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

      if (kind === 'room' && (o.kind === 'tuer' || o.kind === 'durchgang')) {            // Lücke in der Wand, bei Türen mit Schwenkbogen
        svgEl('rect', { class: 'invplan-shape', x: p.x, y: p.y, width: p.w, height: p.h, fill: 'var(--surface2)', stroke: 'var(--text)', 'stroke-opacity': .55, 'stroke-width': 1.5 }, g);
        if (o.kind === 'tuer') {                              // flip: Bit 1 = Anschlag rechts statt links, Bit 2 = Aufschlag nach unten statt oben
          const fh = (o.flip || 0) & 1, fv = ((o.flip || 0) >> 1) & 1, hy = p.y + p.h / 2;
          const hx = fh ? p.x + p.w : p.x, ex = fh ? p.x : p.x + p.w, ly = fv ? hy + p.w : hy - p.w;
          svgEl('path', { d: `M ${hx} ${hy} L ${hx} ${ly} A ${p.w} ${p.w} 0 0 ${fh ^ fv ? 0 : 1} ${ex} ${hy}`, fill: 'none', stroke: 'var(--text)', 'stroke-opacity': .6,
            'stroke-width': 2.5, 'pointer-events': 'none' }, g);
        }
        return;
      }
      if (kind === 'room') {
        const stairs = o.kind === 'treppe';
        const attrs = { class: 'invplan-shape', fill: 'var(--surface)', 'fill-opacity': stairs ? .9 : .65, stroke: 'var(--text)', 'stroke-opacity': .75, 'stroke-width': stairs ? 3 : 6, 'stroke-linejoin': 'round' };
        if (!stairs && o.points) svgEl('polygon', Object.assign({ points: o.points.map(q => q.join(',')).join(' ') }, attrs), g);
        else svgEl('rect', Object.assign({ x: p.x, y: p.y, width: p.w, height: p.h }, attrs), g);
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

    // Grösse ändern an allen vier Kanten (Streifen entlang der Linie) und vier Ecken; die gegenüberliegende Kante bleibt stehen
    const CURSOR = { n: 'ns-resize', s: 'ns-resize', e: 'ew-resize', w: 'ew-resize', nw: 'nwse-resize', se: 'nwse-resize', ne: 'nesw-resize', sw: 'nesw-resize' };
    function drawHandle() {
      const o = find(sel.kind, sel.id);
      if (!o || !o.plan || !visible(sel.kind, o)) return;
      if (sel.kind === 'room' && o.points) {                     // Vieleck: Eckpunkte ziehen, «+» an den Kanten fügt eine Ecke ein
        const g2 = svgEl('g', {}, svg), n = o.points.length;
        o.points.forEach((q, i) => {
          const nx = o.points[(i + 1) % n];
          svgEl('circle', { cx: (q[0] + nx[0]) / 2, cy: (q[1] + nx[1]) / 2, r: 7, fill: 'var(--surface)', stroke: 'var(--accent)', 'stroke-width': 2, 'data-mid': i, style: 'cursor:copy' }, g2);
        });
        o.points.forEach((q, i) => svgEl('circle', { class: 'invplan-handle', cx: q[0], cy: q[1], r: 10, 'data-vertex': i, style: 'cursor:move' }, g2));
        return;
      }
      const p = o.plan, cx = p.x + p.w / 2, cy = p.y + p.h / 2, T = 16;
      const g = svgEl('g', { transform: `rotate(${p.rot || 0} ${cx} ${cy})` }, svg);
      const inH = Math.min(T / 2, p.h * 0.25), inW = Math.min(T / 2, p.w * 0.25);      // nach innen nur wenig, damit Verschieben möglich bleibt
      const strip = (h, x, y, w, ht) => svgEl('rect', { x, y, width: w, height: ht, fill: 'transparent', 'data-handle': h, style: `cursor:${CURSOR[h]}` }, g);
      strip('n', p.x, p.y - T / 2, p.w, T / 2 + inH);
      strip('s', p.x, p.y + p.h - inH, p.w, T / 2 + inH);
      strip('w', p.x - T / 2, p.y, T / 2 + inW, p.h);
      strip('e', p.x + p.w - inW, p.y, T / 2 + inW, p.h);
      const dot = (h, x, y) => svgEl('circle', { class: 'invplan-handle', cx: x, cy: y, r: 9, 'data-handle': h, style: `cursor:${CURSOR[h]}` }, g);
      dot('nw', p.x, p.y); dot('ne', p.x + p.w, p.y); dot('sw', p.x, p.y + p.h); dot('se', p.x + p.w, p.y + p.h);
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
          drag = { mode: 'resize', handle: ev.target.getAttribute('data-handle'), kind: sel.kind, id: sel.id, orig: Object.assign({}, o.plan) };
          svg.setPointerCapture(ev.pointerId);
          return;
        }
        const tgt = ev.target.getAttribute ? ev.target : null;
        if (tgt && sel && sel.kind === 'room' && (tgt.hasAttribute('data-vertex') || tgt.hasAttribute('data-mid'))) {
          const o = find('room', sel.id);
          if (tgt.hasAttribute('data-mid')) {                    // neue Ecke auf der Kantenmitte, sofort ziehbar
            const i = +tgt.getAttribute('data-mid'), a1 = o.points[i], b1 = o.points[(i + 1) % o.points.length];
            if (o.points.length >= 60) return;
            o.points.splice(i + 1, 0, [snap((a1[0] + b1[0]) / 2), snap((a1[1] + b1[1]) / 2)]);
            drag = { mode: 'vertex', kind: 'room', id: sel.id, idx: i + 1, moved: true };
          } else drag = { mode: 'vertex', kind: 'room', id: sel.id, idx: +tgt.getAttribute('data-vertex'), moved: false };
          svg.setPointerCapture(ev.pointerId);
          render();
          return;
        }
        const g = ev.target.closest && ev.target.closest('[data-kind]');
        if (!g) { setSelection(null); return; }
        const kind = g.getAttribute('data-kind'), id = +g.getAttribute('data-id');
        if (!sel || sel.kind !== kind || sel.id !== id) setSelection({ kind, id });
        const oo = find(kind, id);
        drag = { mode: 'move', kind, id, start: pt, orig: Object.assign({}, oo.plan), origPoints: oo.points ? oo.points.map(q => q.slice()) : null, moved: false };
        svg.setPointerCapture(ev.pointerId);
      });
      svg.addEventListener('pointermove', (ev) => {
        if (!drag) return;
        const o = find(drag.kind, drag.id), pt = toCm(ev);
        if (drag.mode === 'vertex') {
          drag.moved = true;
          o.points[drag.idx] = [snap(pt.x), snap(pt.y)];
          fitBox(o);
        } else if (drag.mode === 'move') {
          const dx = pt.x - drag.start.x, dy = pt.y - drag.start.y;
          if (!drag.moved && Math.hypot(dx, dy) < 3) return;
          drag.moved = true;
          const R = data.room;                               // der Mittelpunkt bleibt im Gebäude, sonst gehen Elemente «verloren»
          o.plan.x = clamp(snap(drag.orig.x + dx), -o.plan.w / 2, R.width_cm - o.plan.w / 2);
          o.plan.y = clamp(snap(drag.orig.y + dy), -o.plan.h / 2, R.height_cm - o.plan.h / 2);
          if (drag.origPoints) {                             // Vieleck: alle Ecken um denselben Betrag mitnehmen
            const ddx = o.plan.x - drag.orig.x, ddy = o.plan.y - drag.orig.y;
            o.points = drag.origPoints.map(q => [q[0] + ddx, q[1] + ddy]);
          }
        } else {                                             // Grösse: im Eigensystem des (gedrehten) Elements, Gegenkante bleibt stehen
          const og = drag.orig, h = drag.handle;
          const c0 = { x: og.x + og.w / 2, y: og.y + og.h / 2 };
          const loc = rotateBack(pt, { plan: og });
          let L = og.x, Tp = og.y, R = og.x + og.w, B = og.y + og.h;
          if (h.includes('w')) L = Math.min(snap(loc.x), R - 10);
          if (h.includes('e')) R = Math.max(snap(loc.x), L + 10);
          if (h.includes('n')) Tp = Math.min(snap(loc.y), B - 10);
          if (h.includes('s')) B = Math.max(snap(loc.y), Tp + 10);
          const w = R - L, hh = B - Tp, a = (og.rot || 0) * Math.PI / 180;
          const dx = (L + w / 2) - c0.x, dy = (Tp + hh / 2) - c0.y;      // neue Mitte, in die Welt zurückgedreht
          const cw = { x: c0.x + dx * Math.cos(a) - dy * Math.sin(a), y: c0.y + dx * Math.sin(a) + dy * Math.cos(a) };
          o.plan.w = w; o.plan.h = hh;
          o.plan.x = cw.x - w / 2; o.plan.y = cw.y - hh / 2;
        }
        render();
      });
      const end = () => {
        if (!drag) return;
        const d = drag; drag = null;
        const o = find(d.kind, d.id);
        if ((d.mode === 'move' && d.moved) || d.mode === 'resize' || (d.mode === 'vertex' && d.moved)) { emit(d.kind, o); if (opts.onSelect) opts.onSelect(selInfo()); }
      };
      svg.addEventListener('dblclick', (ev) => {
        const t = ev.target;
        if (!(sel && sel.kind === 'room' && t.getAttribute && t.hasAttribute('data-vertex'))) return;
        const o = find('room', sel.id);
        if (o.points.length <= 3) return;
        o.points.splice(+t.getAttribute('data-vertex'), 1);
        fitBox(o); render(); emit('room', o);
      });
      svg.addEventListener('pointerup', end);
      svg.addEventListener('pointercancel', end);
    }

    function fitBox(o) {                                     // Umgebung der Eckpunkte → plan.x/y/w/h
      const xs = o.points.map(q => q[0]), ys = o.points.map(q => q[1]);
      o.plan.x = Math.min(...xs); o.plan.y = Math.min(...ys);
      o.plan.w = Math.max(5, Math.max(...xs) - o.plan.x); o.plan.h = Math.max(5, Math.max(...ys) - o.plan.y);
    }
    function emit(kind, o) { if (opts.onChange) opts.onChange(kind, o.id, o.plan, kind === 'room' ? { points: o.points || null } : undefined); }

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
        o.plan = { x: clamp(snap(c.x - sz[0] / 2), -sz[0] / 2, data.room.width_cm - sz[0] / 2), y: clamp(snap(c.y - sz[1] / 2), -sz[1] / 2, data.room.height_cm - sz[1] / 2),
          w: sz[0], h: sz[1], rot: 0, floor_id: floor };
        emit(kind, o); setSelection({ kind, id });
      },
      update(kind, id, patch) {
        const o = find(kind, id); if (!o || !o.plan) return;
        const before = Object.assign({}, o.plan);
        Object.assign(o.plan, patch);
        if (o.points && before.w && before.h && ['x', 'y', 'w', 'h'].some(k => k in patch)) {
          o.points = o.points.map(q => [o.plan.x + (q[0] - before.x) / before.w * o.plan.w, o.plan.y + (q[1] - before.y) / before.h * o.plan.h]);
        }
        const R = data.room;
        o.plan.x = clamp(o.plan.x, -o.plan.w / 2, R.width_cm - o.plan.w / 2);
        o.plan.y = clamp(o.plan.y, -o.plan.h / 2, R.height_cm - o.plan.h / 2);
        if (kind !== 'room' && patch.floor_id != null && patch.floor_id !== floor) sel = null;      // auf anderes Stockwerk verschoben
        render(); emit(kind, o);
        if (opts.onSelect) opts.onSelect(selInfo());
      },
      toPolygon(id) {                                        // Rechteck-Raum → Vieleck mit vier Ecken
        const o = find('room', id); if (!o || !o.plan || o.kind !== 'raum' || o.points) return;
        const p = o.plan;
        o.points = [[p.x, p.y], [p.x + p.w, p.y], [p.x + p.w, p.y + p.h], [p.x, p.y + p.h]];
        emit('room', o); setSelection({ kind: 'room', id });
      },
      toRect(id) {                                           // Vieleck → Rechteck der Umgebung
        const o = find('room', id); if (!o || !o.points) return;
        o.points = null;
        emit('room', o); setSelection({ kind: 'room', id });
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
